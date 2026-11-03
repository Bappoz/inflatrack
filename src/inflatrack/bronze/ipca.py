"""Bronze do IPCA/INPC: coleta no SIDRA e gravação nas tabelas Delta, num único ponto de entrada.

Cada resposta do SIDRA vira duas coisas, gravadas no mesmo passo::

    data/parquet/ipca/resposta/     ipca_resposta    uma linha por resposta DIFERENTE
    data/parquet/ipca/observacao/   ipca_observacao  uma linha por valor da resposta
    data/parquet/ipca/metadados/    ipca_metadados   uma linha por versão de categoria da cesta

``ipca_resposta`` guarda o corpo inteiro (valores e metadados) e substituiu os ``.json.gz`` de
``data/raw/``. ``ipca_observacao`` é a entrada do DuckDB e do dbt: tipada, com TODAS as linhas
da resposta, inclusive os marcadores de ausência (``valor`` nulo, ``valor_bruto`` com o texto
original). Descartar marcador, traduzir a categoria para o código da cesta e unir os agregados
são regras de negócio e ficam para o dbt. ``ipca_metadados`` é o que permite essa tradução: os
valores trazem o id interno do SIDRA (``D4C``), e só os metadados dizem qual código e nome ele
tem em cada agregado.

As três tabelas só acrescentam. Reexecutar o mesmo mês não grava nada; se o IBGE revisar um
valor ou renomear um subitem, a revisão entra como linha nova e a anterior permanece (mesma
semântica *insert-only* da tabela ``observacao`` do Postgres, ADR 0001).

O Delta é gravado antes do Postgres, para que uma falha do banco não deixe o formato aberto
para trás; a reexecução não duplica nada em nenhum dos dois. O Postgres continua recebendo a
cesta (``classificacao``, alvo da FK ``produto.codigo_subitem_ipca``) e ``observacao``.

Uso::

    uv run python -m inflatrack.bronze.ipca coletar --agregado 7060 --de 2026-01 --ate 2026-07
    uv run python -m inflatrack.bronze.ipca metadados
    uv run python -m inflatrack.bronze.ipca importar --raw-dir data/raw/ipca-inpc
    uv run python -m inflatrack.bronze.ipca checar

A tabela de respostas é gravada pelo helper comum :mod:`inflatrack.common.bronze`. A tabela de
observações continua aqui, porque filtra as chaves existentes por agregado e mês para não ler
os 9 milhões de linhas a cada mês.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
import psycopg
import pyarrow as pa
import pyarrow.dataset as ds
from deltalake import DeltaTable, write_deltalake

from inflatrack import bronze, sidra
from inflatrack.common.db import dsn_do_ambiente

logger = logging.getLogger("inflatrack.ipca")

FONTE = "ipca"
DIRETORIO_PADRAO = "data/parquet/ipca"

# 13 casas: o número-índice do 1737 chega como "0.0000000076183" (dez/1979).
TIPO_VALOR = pa.decimal128(28, 13)

ESQUEMA_RESPOSTA = bronze.ESQUEMA_RESPOSTA

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

ESQUEMA_METADADOS = bronze.esquema_extraido(
    [
        pa.field("agregado", pa.int16(), nullable=False),
        pa.field("id_categoria", pa.int32(), nullable=False),
        pa.field("codigo", pa.string(), nullable=False),
        pa.field("nome", pa.string(), nullable=False),
        pa.field("codigo_pai", pa.string()),
        pa.field("nivel", pa.string(), nullable=False),
    ]
)

# O nome e o pai entram na chave: renomear um subitem vira uma versão nova, não uma troca.
CHAVE_METADADOS = ("agregado", "id_categoria", "codigo", "nome", "codigo_pai")

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

# Agregados com a classificação 315 (a cesta). O 1737 só tem o índice geral.
AGREGADO_SEM_CESTA = 1737
AGREGADOS_COM_CESTA = tuple(a for a in REFERENCIA if a != AGREGADO_SEM_CESTA)

# Sem limite, uma conexão a um Postgres fora do ar fica minutos pendurada no Windows. O
# valor vale por endereço: `localhost` tenta ::1 e 127.0.0.1, então a falha leva ~2x isso.
TIMEOUT_CONEXAO_S = 5

COLUNAS_OBSERVACAO_POSTGRES = (
    "id_fonte",
    "codigo_classificacao",
    "codigo_localidade",
    "codigo_variavel",
    "mes_referencia",
    "valor",
)

_NOME_ARQUIVO_RAW = re.compile(r"^(?P<agregado>\d+)-(?P<periodo>\d{6})\.json\.gz$")


ChecagemError = bronze.ChecagemError


@dataclass(frozen=True)
class Gravacao:
    """O que uma chamada de :func:`gravar` acrescentou de fato."""

    id_resposta: str
    resposta_nova: bool
    linhas_lidas: int
    linhas_novas: int


hash_do_corpo = bronze.hash_do_corpo


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
    return bronze.gravar_resposta(
        destino,
        FONTE,
        bronze.Resposta(requisicao, status_http, tipo_conteudo, corpo),
        ingerido_em,
    )


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


# --- Metadados da cesta ------------------------------------------------------------


def transformar_metadados(metadados: dict, agregado: int) -> list[dict]:
    """Uma linha por categoria da classificação 315, com o código natural e o nome.

    ``id_categoria`` é o valor que chega em ``D4C``; é por ele que o dbt traduz a
    observação para o código da cesta. O 1737 não tem classificação e devolve lista vazia.
    """
    return [
        {
            "agregado": agregado,
            "id_categoria": int(id_sidra),
            "codigo": codigo,
            "nome": nome,
            "codigo_pai": pai,
            "nivel": sidra.nivel_do_codigo(codigo),
        }
        for id_sidra, codigo, nome, pai in sidra.categorias(metadados)
    ]


def checar_metadados(linhas: list[dict], agregado: int) -> None:
    """Falha se a cesta veio vazia ou muito diferente do tamanho conhecido do agregado."""
    if agregado == AGREGADO_SEM_CESTA:
        return
    esperadas = REFERENCIA[agregado].categorias
    if abs(len(linhas) - esperadas) > esperadas * TOLERANCIA_CATEGORIAS:
        raise ChecagemError(
            f"agregado {agregado}: {len(linhas)} categorias nos metadados (esperado ~{esperadas})"
        )


def gravar_metadados(
    destino: Path, agregado: int, resposta: sidra.Resposta, ingerido_em: datetime | None = None
) -> Gravacao:
    """Guarda a resposta dos metadados e acrescenta as versões novas de categoria."""
    ingerido_em = ingerido_em or datetime.now(UTC)
    linhas = transformar_metadados(resposta.json(), agregado)
    checar_metadados(linhas, agregado)
    id_resposta, nova = gravar_resposta(
        destino,
        requisicao=resposta.url,
        corpo=resposta.corpo,
        ingerido_em=ingerido_em,
        status_http=resposta.status_http,
        tipo_conteudo=resposta.tipo_conteudo,
    )
    novas = bronze.acrescentar(
        destino,
        "metadados",
        _com_metadados(linhas, id_resposta, resposta.url, ingerido_em),
        ESQUEMA_METADADOS,
        CHAVE_METADADOS,
        partition_by=["agregado"],
    )
    return Gravacao(id_resposta, nova, len(linhas), novas)


# --- Postgres: a cesta com vigência e a observação ---------------------------------


def mes_para_data(periodo: str) -> date:
    """``"202607"`` -> ``date(2026, 7, 1)``."""
    return date(int(periodo[:4]), int(periodo[4:]), 1)


def _mes_seguinte(mes: date) -> date:
    return date(mes.year + mes.month // 12, mes.month % 12 + 1, 1)


def _mes_anterior(mes: date) -> date:
    return date(mes.year - (mes.month == 1), (mes.month - 2) % 12 + 1, 1)


def sincronizar_cesta(
    conexao: psycopg.Connection, agregado: int, metadados: dict
) -> dict[str, str]:
    """Insere a classificação e mantém o histórico de versões daquele agregado (SCD tipo 2).

    A versão existe porque o mesmo código muda de nome entre agregados: 43 subitens foram
    renomeados entre 2006 e 2026 (docs/adr/0001). Quando o nome ou o pai mudam, a versão
    aberta é fechada e uma nova é aberta; antes, o ``UPDATE`` apagava o nome antigo.

    A nova versão vale a partir do último mês publicado pelo agregado (``periodicidade.fim``):
    é o primeiro mês em que os metadados atuais podem ter sido vistos. Se a versão aberta
    começou nesse mesmo mês, a nova começa no seguinte, para nunca haver duas faixas iguais.

    Devolve o mapa ``id_sidra -> codigo`` desse agregado: os valores da API identificam a
    categoria pelo ``id`` interno (``D4C``), não pelo código natural gravado em `classificacao`.
    """
    categorias = sidra.categorias(metadados)
    periodo = metadados["periodicidade"]
    inicio_do_agregado = mes_para_data(str(periodo["inicio"]))
    ultimo_publicado = mes_para_data(str(periodo["fim"]))

    with conexao.cursor() as cursor:
        cursor.executemany(
            "insert into classificacao (codigo, nivel) values (%s, %s)"
            " on conflict (codigo) do nothing",
            [(codigo, sidra.nivel_do_codigo(codigo)) for _, codigo, _, _ in categorias],
        )
        cursor.execute(
            "select codigo, nome, codigo_pai, vigencia_inicio from classificacao_versao"
            " where id_fonte = %s and vigencia_fim is null",
            (agregado,),
        )
        abertas = {linha[0]: linha[1:] for linha in cursor.fetchall()}

        fechar, abrir = [], []
        for _, codigo, nome, pai in categorias:
            aberta = abertas.get(codigo)
            if aberta is None:
                abrir.append((codigo, agregado, nome, pai, inicio_do_agregado))
            elif (aberta[0], aberta[1]) != (nome, pai):
                inicio = max(ultimo_publicado, _mes_seguinte(aberta[2]))
                fechar.append((_mes_anterior(inicio), codigo, agregado))
                abrir.append((codigo, agregado, nome, pai, inicio))
                logger.info(
                    "cesta %s/%s: %r -> %r desde %s", agregado, codigo, aberta[0], nome, inicio
                )
        cursor.executemany(
            "update classificacao_versao set vigencia_fim = %s"
            " where codigo = %s and id_fonte = %s and vigencia_fim is null",
            fechar,
        )
        cursor.executemany(
            "insert into classificacao_versao"
            " (codigo, id_fonte, nome, codigo_pai, vigencia_inicio)"
            " values (%s, %s, %s, %s, %s)",
            abrir,
        )
    return {id_sidra: codigo for id_sidra, codigo, _, _ in categorias}


def carregar_periodo(
    conexao: psycopg.Connection,
    agregado: int,
    periodo: str,
    payload: list[dict],
    mapa_classificacao: dict[str, str] | None,
) -> int:
    """Copia um mês para uma tabela temporária e funde em ``observacao``.

    ``mapa_classificacao`` traduz o ``D4C`` (id interno do SIDRA) para o código natural
    gravado em `classificacao` (ver :func:`sincronizar_cesta`). Agregados sem dimensão de
    classificação (1737) não têm ``D4C`` no payload e caem sempre no índice geral.
    """
    mes = mes_para_data(periodo)
    linhas = [
        (
            agregado,
            mapa_classificacao[linha["D4C"]] if mapa_classificacao else sidra.CODIGO_INDICE_GERAL,
            int(linha["D1C"]),
            int(linha["D2C"]),
            mes,
            linha["V"],
        )
        for linha in payload
        if not sidra.eh_ausente(linha["V"])
    ]
    if not linhas:
        return 0

    with conexao.cursor() as cursor:
        cursor.execute(
            "create temp table carga (like observacao including defaults including identity)"
            " on commit drop"
        )
        colunas = ", ".join(COLUNAS_OBSERVACAO_POSTGRES)
        with cursor.copy(f"copy carga ({colunas}) from stdin") as copia:
            for linha in linhas:
                copia.write_row(linha)
        cursor.execute(
            f"insert into observacao ({colunas}) select {colunas} from carga on conflict do nothing"
        )
        return cursor.rowcount


# --- Coleta ------------------------------------------------------------------------


def coletar(args: argparse.Namespace) -> int:
    """Baixa um intervalo de meses de um agregado: Delta primeiro, depois Postgres."""
    inicio, fim = mes_para_data(args.de.replace("-", "")), mes_para_data(args.ate.replace("-", ""))
    destino = Path(args.parquet_dir)
    total = 0

    with (
        httpx.Client() as cliente,
        psycopg.connect(
            args.dsn or dsn_do_ambiente(), connect_timeout=TIMEOUT_CONEXAO_S
        ) as conexao,
    ):
        resposta_metadados = sidra.buscar_metadados_resposta(cliente, args.agregado)
        gravar_metadados(destino, args.agregado, resposta_metadados)
        mapa_classificacao: dict[str, str] | None = None
        if args.agregado != AGREGADO_SEM_CESTA:
            mapa_classificacao = sincronizar_cesta(
                conexao, args.agregado, resposta_metadados.json()
            )
            conexao.commit()
            logger.info(
                "cesta sincronizada: %d categorias do agregado %d",
                len(mapa_classificacao),
                args.agregado,
            )

        niveis, classificacao = sidra.consulta_do_agregado(args.agregado)
        for periodo in sidra.meses(inicio, fim):
            resposta = sidra.buscar_resposta(
                cliente, args.agregado, periodo, niveis=niveis, classificacao=classificacao
            )
            payload = resposta.json()
            if not payload:
                # Mês ainda não divulgado vem como 200 + lista vazia. Falhar (sem gravar nada)
                # mantém a partição pendente no Dagster, e o agendamento tenta no dia seguinte.
                raise sidra.SidraError(f"{args.agregado}/{periodo}: sem dados publicados")
            gravacao = gravar(destino, args.agregado, periodo, resposta)
            logger.info(
                "%s/%s: bronze com %d de %d linhas novas (resposta %s)",
                args.agregado,
                periodo,
                gravacao.linhas_novas,
                gravacao.linhas_lidas,
                "nova" if gravacao.resposta_nova else "já guardada",
            )
            inseridas = carregar_periodo(
                conexao, args.agregado, periodo, payload, mapa_classificacao
            )
            conexao.commit()
            total += inseridas
            logger.info("%s/%s: %d linhas novas", args.agregado, periodo, inseridas)

    logger.info("total inserido: %d linhas", total)
    return total


def coletar_metadados(destino: Path, agregados: Iterable[int] = AGREGADOS_COM_CESTA) -> int:
    """Baixa só os metadados (uma requisição por agregado), sem precisar do Postgres.

    Basta para quem já tem ``observacao`` no Delta: o dbt precisa de ``ipca_metadados`` para
    traduzir ``id_categoria`` em código da cesta, e isso não exige refazer as 886 requisições.
    """
    novas = 0
    with httpx.Client() as cliente:
        for agregado in agregados:
            resposta = sidra.buscar_metadados_resposta(cliente, agregado)
            gravacao = gravar_metadados(destino, agregado, resposta)
            logger.info(
                "metadados %d: %d de %d categorias novas",
                agregado,
                gravacao.linhas_novas,
                gravacao.linhas_lidas,
            )
            novas += gravacao.linhas_novas
    return novas


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


def _comando_coletar(args: argparse.Namespace) -> int:
    coletar(args)
    return 0


def _comando_metadados(args: argparse.Namespace) -> int:
    coletar_metadados(Path(args.parquet_dir), args.agregado or AGREGADOS_COM_CESTA)
    return 0


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

    coleta = comandos.add_parser(
        "coletar", help="SIDRA -> Delta -> Postgres, um intervalo de meses"
    )
    coleta.add_argument(
        "--agregado", type=int, required=True, help="2938, 1419, 7060, 7063 ou 1737"
    )
    coleta.add_argument("--de", required=True, metavar="AAAA-MM")
    coleta.add_argument("--ate", required=True, metavar="AAAA-MM")
    coleta.add_argument("--dsn", default=None, help="padrão: montado do .env")
    coleta.set_defaults(funcao=_comando_coletar)

    meta = comandos.add_parser("metadados", help="só a cesta de cada agregado, sem Postgres")
    meta.add_argument("--agregado", type=int, action="append", help="repita para vários")
    meta.set_defaults(funcao=_comando_metadados)

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
    except (sidra.SidraError, ChecagemError, psycopg.Error, httpx.HTTPError) as erro:
        logger.error("carga abortada: %s", erro)
        return 1


if __name__ == "__main__":
    sys.exit(main())
