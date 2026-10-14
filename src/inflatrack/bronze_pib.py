"""Bronze do PIB e setores (SIDRA 1846): tabela de respostas e tabela extraída, em Delta.

::

    data/parquet/pib/resposta/   pib_resposta   uma linha por resposta DIFERENTE
    data/parquet/pib/valor/      pib_valor      uma linha por valor da resposta

Primeira fonte a usar o helper comum :mod:`inflatrack.bronze`. ``pib_valor`` guarda
todas as linhas da resposta, com o código e o nome do setor como o SIDRA manda e o
texto original em ``valor_bruto``. ``grupo``, ``nucleo``, ``ano`` e ``trimestre`` são
regras de negócio e ficam para o dbt.

Só acrescenta: cada divulgação do IBGE revisa trimestres anteriores, e a revisão entra
como linha nova, sem apagar a anterior. Reexecutar sem revisão não grava nada.

Uso::

    uv run python -m inflatrack.bronze_pib importar --raw-dir data/raw/pib_raw
    uv run python -m inflatrack.bronze_pib checar
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
import pyarrow as pa

from inflatrack import bronze, pib, sidra
from inflatrack.bronze import ChecagemError

logger = logging.getLogger("inflatrack.bronze_pib")

FONTE = "pib"
DIRETORIO_PADRAO = "data/parquet/pib"
TABELA = "valor"

CATEGORIAS_POR_TRIMESTRE = 23
UNIDADE = 1550  # Milhões de Reais
CAMPOS = frozenset({"NC", "MC", "V", "D1C", "D2C", "D3C", "D4C"})

ESQUEMA_VALOR = bronze.esquema_extraido(
    [
        pa.field("data_referencia", pa.date32(), nullable=False),
        pa.field("codigo_setor", pa.string(), nullable=False),
        pa.field("nome_setor", pa.string()),
        pa.field("nivel_territorial", pa.int16(), nullable=False),
        pa.field("codigo_localidade", pa.int32(), nullable=False),
        pa.field("codigo_variavel", pa.int32(), nullable=False),
        pa.field("codigo_unidade", pa.int16()),
        pa.field("valor", pa.decimal128(20, 4)),
        pa.field("valor_bruto", pa.string(), nullable=False),
    ]
)

# O valor entra na chave: é o que faz a revisão do IBGE virar linha nova.
CHAVE = ("data_referencia", "codigo_setor", "valor_bruto")

_NOME_ARQUIVO_RAW = re.compile(r"^1846-(?P<ano>\d{4})\.json\.gz$")


@dataclass(frozen=True)
class Gravacao:
    respostas_novas: int
    linhas_lidas: int
    linhas_novas: int


def _decimal(texto: str) -> Decimal | None:
    if sidra.eh_ausente(texto):
        return None
    try:
        return Decimal(texto)
    except InvalidOperation as erro:
        raise ChecagemError(f"valor que não é número nem marcador conhecido: {texto!r}") from erro


def nomes_dos_setores(metadados: dict) -> dict[str, str]:
    """``codigo -> nome`` da classificação c11255, como os metadados mandam."""
    return {codigo: nome for codigo, nome, _, _ in pib.setores(metadados)}


def transformar(payload: list[dict[str, str]], nomes: dict[str, str]) -> list[dict]:
    """Achata a resposta em linhas tipadas, uma por objeto, sem descartar nada.

    ``D3C`` (``"199603"``, ano e trimestre) vira o primeiro dia do trimestre. Setor
    ausente dos metadados fica com ``nome_setor`` nulo, em vez de um nome inventado.
    """
    linhas = []
    for objeto in payload:
        if objeto.keys() != CAMPOS:
            raise ChecagemError(f"campos {sorted(objeto)} diferentes de {sorted(CAMPOS)}")
        codigo = objeto["D4C"]
        linhas.append(
            {
                "data_referencia": pib.trimestre_para_data(objeto["D3C"]),
                "codigo_setor": codigo,
                "nome_setor": nomes.get(codigo),
                "nivel_territorial": int(objeto["NC"]),
                "codigo_localidade": int(objeto["D1C"]),
                "codigo_variavel": int(objeto["D2C"]),
                "codigo_unidade": int(objeto["MC"]) if objeto["MC"] else None,
                "valor": _decimal(objeto["V"]),
                "valor_bruto": objeto["V"],
            }
        )
    return linhas


def checar(linhas: list[dict], ano: int, hoje: date | None = None) -> None:
    """Checagens de um ano antes de promovê-lo à Bronze.

    Cada trimestre presente tem as 23 categorias, uma vez cada, só Brasil, variável 585
    e unidade milhões de reais. Os trimestres começam no 1º, sem buraco. Anos anteriores
    ao ano passado precisam dos 4 trimestres: o 4º trimestre só sai em março.
    """
    hoje = hoje or date.today()
    if not linhas:
        raise ChecagemError(f"{ano}: resposta vazia")

    problemas = []
    if {linha["data_referencia"].year for linha in linhas} != {ano}:
        problemas.append("trimestres de outro ano na resposta")
    if {linha["nivel_territorial"] for linha in linhas} != {1}:
        problemas.append("nível territorial diferente de Brasil")
    if {linha["codigo_variavel"] for linha in linhas} != {pib.VARIAVEL}:
        problemas.append(f"variável diferente de {pib.VARIAVEL}")
    unidades = {linha["codigo_unidade"] for linha in linhas if linha["valor"] is not None}
    if unidades - {UNIDADE}:
        problemas.append(f"unidades {sorted(unidades)} (esperado {UNIDADE})")

    por_trimestre: dict[date, list[str]] = {}
    for linha in linhas:
        por_trimestre.setdefault(linha["data_referencia"], []).append(linha["codigo_setor"])
    for referencia, setores in sorted(por_trimestre.items()):
        if len(setores) != len(set(setores)):
            problemas.append(f"{referencia}: setor repetido")
        if len(set(setores)) != CATEGORIAS_POR_TRIMESTRE:
            problemas.append(
                f"{referencia}: {len(set(setores))} setores (esperado {CATEGORIAS_POR_TRIMESTRE})"
            )

    trimestres = sorted((referencia.month + 2) // 3 for referencia in por_trimestre)
    if trimestres != list(range(1, len(trimestres) + 1)):
        problemas.append(f"trimestres {trimestres} com buraco")
    if ano < hoje.year - 1 and len(trimestres) != 4:
        problemas.append(f"ano passado com {len(trimestres)} trimestres (esperado 4)")

    if problemas:
        raise ChecagemError(f"{ano}: " + "; ".join(problemas))


def requisicao_do_ano(ano: int) -> str:
    return sidra.url_valores(
        pib.AGREGADO,
        pib.periodo_do_ano(ano),
        niveis=pib.NIVEIS,
        classificacao=pib.CLASSIFICACAO,
    )


def _extrair(
    destino: Path,
    resposta: bronze.Resposta,
    payload: list[dict],
    ano: int,
    nomes: dict[str, str],
    ingerido_em: datetime,
) -> tuple[bool, list[dict]]:
    """Checa, guarda a resposta e devolve as linhas com metadados (ainda não gravadas)."""
    linhas = transformar(payload, nomes)
    checar(linhas, ano, hoje=ingerido_em.date())
    id_resposta, nova = bronze.gravar_resposta(destino, FONTE, resposta, ingerido_em)
    return nova, bronze.com_metadados(
        linhas,
        id_resposta=id_resposta,
        fonte=FONTE,
        requisicao=resposta.url,
        ingerido_em=ingerido_em,
    )


def guardar_metadados(destino: Path, resposta: bronze.Resposta, ingerido_em: datetime) -> dict:
    """Guarda a resposta de metadados (origem dos nomes) e devolve o JSON."""
    metadados = json.loads(resposta.corpo)
    nomes_dos_setores(metadados)  # falha antes de gravar se faltar a classificação
    bronze.gravar_resposta(destino, FONTE, resposta, ingerido_em)
    return metadados


def gravar_anos(
    destino: Path,
    respostas: list[tuple[int, bronze.Resposta]],
    nomes: dict[str, str],
    ingerido_em: datetime | None = None,
) -> Gravacao:
    """Grava os anos nas duas tabelas. Um único commit em ``pib_valor`` por execução."""
    ingerido_em = ingerido_em or datetime.now(UTC)
    novas_respostas, linhas = 0, []
    for ano, resposta in respostas:
        nova, extraidas = _extrair(
            destino, resposta, json.loads(resposta.corpo), ano, nomes, ingerido_em
        )
        novas_respostas += nova
        linhas.extend(extraidas)
    novas = bronze.acrescentar(destino, TABELA, linhas, ESQUEMA_VALOR, CHAVE)
    return Gravacao(novas_respostas, len(linhas), novas)


# --- Importação do Raw antigo -----------------------------------------------------


def importar_raw(raw_dir: Path, destino: Path, metadados: bronze.Resposta) -> Gravacao:
    """Leva os ``1846-AAAA.json.gz`` de ``data/raw/pib_raw/`` para as duas tabelas.

    O Raw não guardou os metadados, então os nomes vêm de ``metadados`` (baixado na
    hora). Como no IPCA, ``corpo`` é o JSON regravado pelo ingestor antigo,
    ``status_http`` e ``tipo_conteudo`` ficam nulos, ``_requisicao`` é reconstruída
    pelo ano e ``_ingerido_em`` é a data de modificação do arquivo.
    """
    agora = datetime.now(UTC)
    nomes = nomes_dos_setores(guardar_metadados(destino, metadados, agora))
    novas_respostas, linhas = 0, []
    for arquivo in sorted(raw_dir.glob("*.json.gz")):
        casou = _NOME_ARQUIVO_RAW.match(arquivo.name)
        if not casou:
            logger.warning("ignorado (nome fora do padrão): %s", arquivo.name)
            continue
        ano = int(casou["ano"])
        corpo = bronze.ler_gz(arquivo)
        resposta = bronze.Resposta(requisicao_do_ano(ano), None, None, corpo)
        ingerido_em = datetime.fromtimestamp(arquivo.stat().st_mtime, UTC)
        nova, extraidas = _extrair(destino, resposta, json.loads(corpo), ano, nomes, ingerido_em)
        novas_respostas += nova
        linhas.extend(extraidas)
    novas = bronze.acrescentar(destino, TABELA, linhas, ESQUEMA_VALOR, CHAVE)
    return Gravacao(novas_respostas, len(linhas), novas)


# --- Checagem da tabela gravada ---------------------------------------------------


def resumo_da_bronze(destino: Path) -> dict:
    """Trimestres, buracos, setores por trimestre e revisões de ``pib_valor``."""
    import duckdb

    valor = bronze.ler(destino, TABELA)  # noqa: F841 (lida pelo DuckDB)
    respostas = bronze.ler(destino, "resposta")  # noqa: F841
    linha = duckdb.sql(
        """
        with por_trimestre as (
            select data_referencia,
                   count(distinct codigo_setor) as setores,
                   count(*) as linhas
            from valor group by all
        )
        select min(data_referencia), max(data_referencia), count(*),
               sum(linhas), sum(setores),
               count(*) filter (where setores <> 23),
               sum(linhas - setores),
               (select count(*) from valor where valor is null),
               (select count(*) from respostas)
        from por_trimestre
        """
    ).fetchone()
    primeiro, ultimo = linha[0], linha[1]
    esperados = (ultimo.year - primeiro.year) * 4 + (ultimo.month - primeiro.month) // 3 + 1
    return {
        "primeiro_trimestre": primeiro,
        "ultimo_trimestre": ultimo,
        "trimestres": linha[2],
        "trimestres_faltando": esperados - linha[2],
        "linhas": linha[3],
        "valores_distintos": linha[4],
        "trimestres_fora_de_23_setores": linha[5],
        "linhas_de_revisao": linha[6],
        "linhas_sem_valor": linha[7],
        "respostas": linha[8],
    }


def _comando_importar(args: argparse.Namespace) -> int:
    with httpx.Client() as cliente:
        metadados = sidra.buscar_metadados_resposta(cliente, pib.AGREGADO)
    gravacao = importar_raw(Path(args.raw_dir), Path(args.parquet_dir), metadados)
    logger.info(
        "importação: %d respostas novas, %d de %d linhas novas",
        gravacao.respostas_novas,
        gravacao.linhas_novas,
        gravacao.linhas_lidas,
    )
    return 0


def _comando_checar(args: argparse.Namespace) -> int:
    resumo = resumo_da_bronze(Path(args.parquet_dir))
    print(" ".join(f"{coluna}={valor}" for coluna, valor in resumo.items()))
    reprovado = resumo["trimestres_faltando"] or resumo["trimestres_fora_de_23_setores"]
    return 1 if reprovado else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--parquet-dir", default=DIRETORIO_PADRAO)
    comandos = parser.add_subparsers(dest="comando", required=True)

    importar = comandos.add_parser("importar", help="leva data/raw/pib_raw/ para o Delta")
    importar.add_argument("--raw-dir", default="data/raw/pib_raw")
    importar.set_defaults(funcao=_comando_importar)

    checar_cmd = comandos.add_parser("checar", help="trimestres, setores e revisões")
    checar_cmd.set_defaults(funcao=_comando_checar)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return args.funcao(args)
    except (ChecagemError, sidra.SidraError, httpx.HTTPError) as erro:
        logger.error("%s", erro)
        return 1


if __name__ == "__main__":
    sys.exit(main())
