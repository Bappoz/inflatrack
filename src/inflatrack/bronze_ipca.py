"""Bronze do IPCA/INPC: tabela de respostas e tabela extraída, em Delta.

Cada resposta do SIDRA vira duas coisas, gravadas no mesmo passo::

    data/parquet/ipca/resposta/     ipca_resposta    uma linha por resposta DIFERENTE
    data/parquet/ipca/observacao/   ipca_observacao  uma linha por valor da resposta

``ipca_resposta`` guarda o corpo inteiro e substitui os ``.json.gz`` de ``data/raw/``.
``ipca_observacao`` é a entrada do DuckDB e do dbt: tipada, com TODAS as linhas da
resposta, inclusive os marcadores de ausência (``valor`` nulo, ``valor_bruto`` com o
texto original). Descartar marcador, traduzir a categoria para o código da cesta e
unir os agregados são regras de negócio e ficam para o dbt.

As duas tabelas só acrescentam. Reexecutar o mesmo mês não grava nada; se o IBGE
revisar um valor, a revisão entra como linha nova e a anterior permanece (mesma
semântica *insert-only* da tabela ``observacao`` do Postgres, ADR 0001).

Uso::

    uv run python -m inflatrack.bronze_ipca importar --raw-dir data/raw/ipca-inpc
    uv run python -m inflatrack.bronze_ipca checar

Este módulo é da fonte IPCA. Quando o helper comum ``inflatrack/bronze.py`` (contrato
4.1 do plano) existir, :func:`gravar_resposta` e :func:`acrescentar_observacoes` passam
a delegar para ele; os nomes de coluna já seguem a seção 2.2 do plano.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as ds
from deltalake import DeltaTable, write_deltalake

from inflatrack import sidra

logger = logging.getLogger("inflatrack.bronze_ipca")

FONTE = "ipca"
DIRETORIO_PADRAO = "data/parquet/ipca"

# 13 casas: o número-índice do 1737 chega como "0.0000000076183" (dez/1979).
TIPO_VALOR = pa.decimal128(28, 13)

ESQUEMA_RESPOSTA = pa.schema(
    [
        pa.field("id_resposta", pa.string(), nullable=False),
        pa.field("_fonte", pa.string(), nullable=False),
        pa.field("_requisicao", pa.string(), nullable=False),
        pa.field("_ingerido_em", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("status_http", pa.int16()),
        pa.field("tipo_conteudo", pa.string()),
        pa.field("corpo", pa.string(), nullable=False),
        pa.field("hash_corpo", pa.string(), nullable=False),
        pa.field("tamanho_bytes", pa.int64(), nullable=False),
    ]
)

ESQUEMA_OBSERVACAO = pa.schema(
    [
        pa.field("agregado", pa.int16(), nullable=False),
        pa.field("mes_referencia", pa.date32(), nullable=False),
        pa.field("nivel_territorial", pa.int16(), nullable=False),
        pa.field("codigo_localidade", pa.int32(), nullable=False),
        pa.field("codigo_variavel", pa.int32(), nullable=False),
        pa.field("id_categoria", pa.int32()),
        pa.field("codigo_unidade", pa.int16()),
        pa.field("valor", TIPO_VALOR),
        pa.field("valor_bruto", pa.string(), nullable=False),
        pa.field("_id_resposta", pa.string(), nullable=False),
        pa.field("_fonte", pa.string(), nullable=False),
        pa.field("_requisicao", pa.string(), nullable=False),
        pa.field("_ingerido_em", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

# Uma observação é "a mesma" quando repete estas colunas. O valor entra na chave de
# propósito: é o que faz a revisão do IBGE virar linha nova em vez de ser ignorada.
CHAVE_OBSERVACAO = (
    "mes_referencia",
    "codigo_localidade",
    "codigo_variavel",
    "id_categoria",
    "valor_bruto",
)

CAMPOS_COM_CLASSIFICACAO = frozenset({"NC", "MC", "V", "D1C", "D2C", "D3C", "D4C"})
CAMPOS_SEM_CLASSIFICACAO = CAMPOS_COM_CLASSIFICACAO - {"D4C"}


@dataclass(frozen=True)
class Referencia:
    """Forma esperada de um mês completo de um agregado (medida na API em 2026-10-11)."""

    localidades: int
    variaveis: frozenset[int]
    categorias: int

    @property
    def linhas(self) -> int:
        return self.localidades * len(self.variaveis) * self.categorias


# A resposta é sempre um retângulo localidade x variável x categoria: onde não há
# dado, a API manda um marcador, não omite a linha. Por isso o volume é exato.
REFERENCIA = {
    2938: Referencia(12, frozenset({63, 66, 69}), 465),  # 16.740 linhas/mês
    1419: Referencia(17, frozenset({63, 66, 69, 2265}), 464),  # 31.552
    7060: Referencia(17, frozenset({63, 66, 69, 2265}), 457),  # 31.076
    7063: Referencia(17, frozenset({44, 45, 68, 2292}), 447),  # 30.396
    1737: Referencia(1, frozenset({63, 69, 2263, 2264, 2265, 2266}), 1),  # 6
}

# A cesta ganha e perde subitem sem trocar de agregado; variação maior que esta no
# número de categorias indica resposta truncada ou mudança de estrutura a investigar.
TOLERANCIA_CATEGORIAS = 0.05

_NOME_ARQUIVO_RAW = re.compile(r"^(?P<agregado>\d+)-(?P<periodo>\d{6})\.json\.gz$")


class ChecagemError(ValueError):
    """A resposta não tem a forma esperada e não deve ser promovida à Bronze."""


@dataclass(frozen=True)
class Gravacao:
    """O que uma chamada de :func:`gravar` acrescentou de fato."""

    id_resposta: str
    resposta_nova: bool
    linhas_lidas: int
    linhas_novas: int


def hash_do_corpo(corpo: str) -> str:
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()


def _inteiro(texto: str) -> int | None:
    """Campo de código: vazio vira nulo (a unidade vem vazia nas linhas sem valor)."""
    return int(texto) if texto != "" else None


def _decimal(texto: str) -> Decimal | None:
    """``"-0.67"`` é deflação e vira número; ``"-"`` sozinho é marcador e vira nulo."""
    if sidra.eh_ausente(texto):
        return None
    try:
        return Decimal(texto)
    except InvalidOperation as erro:
        raise ChecagemError(f"valor que não é número nem marcador conhecido: {texto!r}") from erro


def transformar(payload: list[dict[str, str]], agregado: int) -> list[dict]:
    """Achata a resposta do SIDRA em linhas tipadas, sem descartar nem derivar nada.

    Uma linha de saída por objeto da resposta, na mesma ordem. Todos os campos que a
    API manda são mantidos; nenhum valor padrão é inventado para campo ausente:

    ====== =================== ==================================================
    SIDRA  Coluna              Conversão
    ====== =================== ==================================================
    NC     nivel_territorial   inteiro (1 Brasil, 6 município, 7 região metrop.)
    D1C    codigo_localidade   inteiro
    D2C    codigo_variavel     inteiro
    D3C    mes_referencia      ``"202609"`` -> dia 1 do mês
    D4C    id_categoria        inteiro; nulo no 1737, que não tem classificação
    MC     codigo_unidade      inteiro; nulo quando a API manda vazio
    V      valor               decimal; nulo para ``...``, ``..``, ``-`` e ``X``
    V      valor_bruto         o texto exatamente como veio
    ====== =================== ==================================================

    ``id_categoria`` é o id interno do SIDRA, não o código da cesta (``1101002``):
    a tradução depende dos metadados do agregado e é feita no dbt.
    """
    esperados = CAMPOS_SEM_CLASSIFICACAO if agregado == 1737 else CAMPOS_COM_CLASSIFICACAO
    linhas = []
    for objeto in payload:
        if objeto.keys() != esperados:
            raise ChecagemError(
                f"agregado {agregado}: campos {sorted(objeto)} diferentes de {sorted(esperados)}"
            )
        periodo = objeto["D3C"]
        linhas.append(
            {
                "agregado": agregado,
                "mes_referencia": date(int(periodo[:4]), int(periodo[4:]), 1),
                "nivel_territorial": int(objeto["NC"]),
                "codigo_localidade": int(objeto["D1C"]),
                "codigo_variavel": int(objeto["D2C"]),
                "id_categoria": int(objeto["D4C"]) if "D4C" in objeto else None,
                "codigo_unidade": _inteiro(objeto["MC"]),
                "valor": _decimal(objeto["V"]),
                "valor_bruto": objeto["V"],
            }
        )
    return linhas


def checar(linhas: list[dict], agregado: int, periodo: str | None = None) -> None:
    """Checagens de esquema e volume de um mês, antes de promovê-lo à Bronze.

    Falha com :class:`ChecagemError` quando o mês não é um retângulo completo
    localidade x variável x categoria com as dimensões de :data:`REFERENCIA`.
    """
    referencia = REFERENCIA[agregado]
    if not linhas:
        raise ChecagemError(f"agregado {agregado}: resposta vazia")

    meses = {linha["mes_referencia"] for linha in linhas}
    if len(meses) != 1:
        raise ChecagemError(f"agregado {agregado}: mais de um mês na resposta ({sorted(meses)})")
    (mes,) = meses
    if periodo is not None and mes.strftime("%Y%m") != periodo:
        raise ChecagemError(f"agregado {agregado}: pedido {periodo}, recebido {mes:%Y%m}")

    localidades = {linha["codigo_localidade"] for linha in linhas}
    variaveis = {linha["codigo_variavel"] for linha in linhas}
    categorias = {linha["id_categoria"] for linha in linhas}
    problemas = []
    if len(localidades) != referencia.localidades:
        problemas.append(f"{len(localidades)} localidades (esperado {referencia.localidades})")
    if variaveis != referencia.variaveis:
        problemas.append(f"variáveis {sorted(variaveis)} (esperado {sorted(referencia.variaveis)})")
    if abs(len(categorias) - referencia.categorias) > referencia.categorias * TOLERANCIA_CATEGORIAS:
        problemas.append(f"{len(categorias)} categorias (esperado ~{referencia.categorias})")

    # Retângulo sem buraco e sem repetição: toda combinação aparece exatamente uma vez.
    combinacoes = {
        (linha["codigo_localidade"], linha["codigo_variavel"], linha["id_categoria"])
        for linha in linhas
    }
    completo = len(localidades) * len(variaveis) * len(categorias)
    if len(linhas) != len(combinacoes):
        problemas.append(f"{len(linhas) - len(combinacoes)} combinações repetidas")
    if len(combinacoes) != completo:
        problemas.append(f"{len(combinacoes)} combinações de {completo} possíveis")

    if problemas:
        raise ChecagemError(f"agregado {agregado}, {mes:%Y-%m}: " + "; ".join(problemas))


def _caminho(destino: Path, tabela: str) -> str:
    return str(destino / tabela)


def gravar_resposta(
    destino: Path,
    *,
    requisicao: str,
    corpo: str,
    ingerido_em: datetime,
    status_http: int | None,
    tipo_conteudo: str | None,
) -> tuple[str, bool]:
    """Guarda o corpo da resposta, a menos que um corpo idêntico já esteja guardado.

    Devolve ``(id_resposta, nova)``. O id é o SHA-256 do corpo, então a tabela tem
    exatamente uma linha por versão diferente que a fonte publicou.
    """
    caminho = _caminho(destino, "resposta")
    id_resposta = hash_do_corpo(corpo)
    if DeltaTable.is_deltatable(caminho):
        existentes = (
            DeltaTable(caminho)
            .to_pyarrow_dataset()
            .to_table(columns=["hash_corpo"], filter=ds.field("hash_corpo") == id_resposta)
        )
        if existentes.num_rows:
            return id_resposta, False

    linha = {
        "id_resposta": id_resposta,
        "_fonte": FONTE,
        "_requisicao": requisicao,
        "_ingerido_em": ingerido_em,
        "status_http": status_http,
        "tipo_conteudo": tipo_conteudo,
        "corpo": corpo,
        "hash_corpo": id_resposta,
        "tamanho_bytes": len(corpo.encode("utf-8")),
    }
    write_deltalake(caminho, pa.Table.from_pylist([linha], ESQUEMA_RESPOSTA), mode="append")
    return id_resposta, True


def _chave(linha: dict) -> tuple:
    return tuple(linha[coluna] for coluna in CHAVE_OBSERVACAO)


def _chaves_existentes(caminho: str, agregado: int, meses: Iterable[date]) -> set[tuple]:
    if not DeltaTable.is_deltatable(caminho):
        return set()
    filtro = (ds.field("agregado") == agregado) & ds.field("mes_referencia").isin(list(meses))
    tabela = (
        DeltaTable(caminho)
        .to_pyarrow_dataset()
        .to_table(columns=list(CHAVE_OBSERVACAO), filter=filtro)
    )
    colunas = [tabela.column(coluna).to_pylist() for coluna in CHAVE_OBSERVACAO]
    return set(zip(*colunas, strict=True))


def acrescentar_observacoes(destino: Path, agregado: int, linhas: list[dict]) -> int:
    """Acrescenta só as linhas que ainda não existem e devolve quantas entraram.

    ``linhas`` já traz os metadados (``_id_resposta`` etc.). Linha já gravada com o
    mesmo valor é ignorada, e isso é o que torna a reexecução um no-op; valor
    diferente para a mesma combinação é revisão e entra como linha nova.
    """
    if not linhas:
        return 0
    caminho = _caminho(destino, "observacao")
    existentes = _chaves_existentes(
        caminho, agregado, {linha["mes_referencia"] for linha in linhas}
    )
    novas = [linha for linha in linhas if _chave(linha) not in existentes]
    if novas:
        write_deltalake(
            caminho,
            pa.Table.from_pylist(novas, ESQUEMA_OBSERVACAO),
            mode="append",
            partition_by=["agregado"],
        )
    return len(novas)


def _com_metadados(
    linhas: list[dict], id_resposta: str, requisicao: str, ingerido_em: datetime
) -> list[dict]:
    metadados = {
        "_id_resposta": id_resposta,
        "_fonte": FONTE,
        "_requisicao": requisicao,
        "_ingerido_em": ingerido_em,
    }
    return [linha | metadados for linha in linhas]


def gravar(
    destino: Path,
    agregado: int,
    periodo: str,
    resposta: sidra.Resposta,
    ingerido_em: datetime | None = None,
) -> Gravacao:
    """Grava um mês nas duas tabelas. Chamado pelo ingestor a cada requisição.

    A checagem roda antes de qualquer escrita: resposta vazia ou fora da forma
    esperada não entra em nenhuma das duas tabelas.
    """
    ingerido_em = ingerido_em or datetime.now(UTC)
    linhas = transformar(resposta.json(), agregado)
    checar(linhas, agregado, periodo)
    id_resposta, nova = gravar_resposta(
        destino,
        requisicao=resposta.url,
        corpo=resposta.corpo,
        ingerido_em=ingerido_em,
        status_http=resposta.status_http,
        tipo_conteudo=resposta.tipo_conteudo,
    )
    novas = acrescentar_observacoes(
        destino, agregado, _com_metadados(linhas, id_resposta, resposta.url, ingerido_em)
    )
    return Gravacao(id_resposta, nova, len(linhas), novas)


# --- Importação do Raw antigo -----------------------------------------------------


def arquivos_raw(
    raw_dir: Path, agregados: set[int] | None = None
) -> Iterator[tuple[int, str, Path]]:
    """``(agregado, periodo, caminho)`` de cada ``{agregado}-{AAAAMM}.json.gz``, em ordem."""
    for caminho in sorted(raw_dir.glob("*.json.gz")):
        casou = _NOME_ARQUIVO_RAW.match(caminho.name)
        if not casou:
            logger.warning("ignorado (nome fora do padrão): %s", caminho.name)
            continue
        agregado = int(casou["agregado"])
        if agregados is None or agregado in agregados:
            yield agregado, casou["periodo"], caminho


def importar_raw(
    raw_dir: Path,
    destino: Path,
    agregados: set[int] | None = None,
    lote: int = 12,
) -> tuple[int, int, list[str]]:
    """Leva os ``.json.gz`` de ``data/raw/ipca-inpc/`` para as duas tabelas Delta.

    O que a importação NÃO consegue recuperar, e por isso grava como nulo ou
    aproxima, em vez de inventar:

    * ``corpo`` é o texto do arquivo, isto é, o JSON que o ingestor antigo
      regravou, e não os bytes originais da API. Por isso o hash de uma resposta
      importada difere do hash da mesma resposta baixada de novo.
    * ``status_http`` e ``tipo_conteudo`` não foram guardados: ficam nulos.
    * ``_requisicao`` é reconstruída pelo nome do arquivo (agregado e mês).
    * ``_ingerido_em`` é a data de modificação do arquivo.

    Arquivo que falha na checagem tem o corpo guardado, mas não é extraído. Devolve
    ``(respostas novas, observações novas, falhas)``.
    """
    respostas = observacoes = 0
    falhas: list[str] = []
    pendentes: dict[int, list[dict]] = {}
    meses_pendentes: dict[int, int] = {}

    def descarregar(agregado: int) -> None:
        nonlocal observacoes
        observacoes += acrescentar_observacoes(destino, agregado, pendentes.pop(agregado, []))
        meses_pendentes.pop(agregado, None)

    for agregado, periodo, caminho in arquivos_raw(raw_dir, agregados):
        with gzip.open(caminho, "rt", encoding="utf-8") as arquivo:
            corpo = arquivo.read()
        niveis, classificacao = sidra.consulta_do_agregado(agregado)
        requisicao = sidra.url_valores(
            agregado, periodo, niveis=niveis, classificacao=classificacao
        )
        ingerido_em = datetime.fromtimestamp(caminho.stat().st_mtime, UTC)

        id_resposta, nova = gravar_resposta(
            destino,
            requisicao=requisicao,
            corpo=corpo,
            ingerido_em=ingerido_em,
            status_http=None,
            tipo_conteudo=None,
        )
        respostas += nova
        try:
            linhas = transformar(json.loads(corpo), agregado)
            checar(linhas, agregado, periodo)
        except ChecagemError as erro:
            falhas.append(f"{caminho.name}: {erro}")
            logger.error("%s: corpo guardado, extração recusada: %s", caminho.name, erro)
            continue

        pendentes.setdefault(agregado, []).extend(
            _com_metadados(linhas, id_resposta, requisicao, ingerido_em)
        )
        meses_pendentes[agregado] = meses_pendentes.get(agregado, 0) + 1
        # Um commit por lote de meses, e não por arquivo, para não criar ~900 Parquets.
        if meses_pendentes[agregado] >= lote:
            descarregar(agregado)
        logger.info("%s importado", caminho.name)

    for agregado in list(pendentes):
        descarregar(agregado)
    return respostas, observacoes, falhas


# --- Checagem das tabelas já gravadas ---------------------------------------------


def resumo_da_bronze(destino: Path) -> list[dict]:
    """Uma linha por agregado: meses, buracos na sequência, volume e revisões.

    ``meses_fora_do_volume`` conta meses cujo número de combinações distintas difere
    do retângulo de :data:`REFERENCIA`; ``linhas_de_revisao`` conta as linhas a mais
    que a mesma combinação recebeu (um valor republicado pelo IBGE).
    """
    import duckdb

    caminho = _caminho(destino, "observacao")
    if not DeltaTable.is_deltatable(caminho):
        raise ChecagemError(f"não há tabela Delta em {caminho}")
    observacao = DeltaTable(caminho).to_pyarrow_dataset()  # noqa: F841 (lida pelo DuckDB)
    por_mes = duckdb.sql(
        """
        select agregado, mes_referencia,
               count(*) as linhas,
               count(distinct (codigo_localidade, codigo_variavel, coalesce(id_categoria, 0)))
                   as combinacoes,
               count(*) filter (where valor is null) as sem_valor
        from observacao
        group by all
        """
    ).fetchall()

    saida = []
    for agregado in sorted({linha[0] for linha in por_mes}):
        meses = sorted(linha for linha in por_mes if linha[0] == agregado)
        primeiro, ultimo = meses[0][1], meses[-1][1]
        esperados = (ultimo.year - primeiro.year) * 12 + ultimo.month - primeiro.month + 1
        referencia = REFERENCIA[agregado].linhas
        saida.append(
            {
                "agregado": agregado,
                "primeiro_mes": primeiro,
                "ultimo_mes": ultimo,
                "meses": len(meses),
                "meses_faltando": esperados - len(meses),
                "linhas": sum(linha[2] for linha in meses),
                "linhas_por_mes_esperadas": referencia,
                "meses_fora_do_volume": sum(1 for linha in meses if linha[3] != referencia),
                "linhas_de_revisao": sum(linha[2] - linha[3] for linha in meses),
                "linhas_sem_valor": sum(linha[4] for linha in meses),
            }
        )
    return saida


def _comando_importar(args: argparse.Namespace) -> int:
    agregados = set(args.agregado) if args.agregado else None
    respostas, observacoes, falhas = importar_raw(
        Path(args.raw_dir), Path(args.parquet_dir), agregados
    )
    logger.info("importação: %d respostas novas, %d observações novas", respostas, observacoes)
    return 1 if falhas else 0


def _comando_checar(args: argparse.Namespace) -> int:
    resumo = resumo_da_bronze(Path(args.parquet_dir))
    for linha in resumo:
        print(" ".join(f"{coluna}={valor}" for coluna, valor in linha.items()))
    reprovado = any(linha["meses_faltando"] or linha["meses_fora_do_volume"] for linha in resumo)
    return 1 if reprovado else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--parquet-dir", default=DIRETORIO_PADRAO)
    comandos = parser.add_subparsers(dest="comando", required=True)

    importar = comandos.add_parser("importar", help="leva data/raw/ipca-inpc/ para o Delta")
    importar.add_argument("--raw-dir", default="data/raw/ipca-inpc")
    importar.add_argument("--agregado", type=int, action="append", help="repita para vários")
    importar.set_defaults(funcao=_comando_importar)

    checar_cmd = comandos.add_parser("checar", help="volume e buracos de ipca_observacao")
    checar_cmd.set_defaults(funcao=_comando_checar)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return args.funcao(args)
    except ChecagemError as erro:
        logger.error("%s", erro)
        return 1


if __name__ == "__main__":
    sys.exit(main())
