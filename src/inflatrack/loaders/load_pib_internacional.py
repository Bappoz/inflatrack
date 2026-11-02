"""Carga das tabelas Delta do PIB Internacional no DuckDB analítico compartilhado.

Espelha as tabelas Delta de China, EUA e Rússia em:
  - ``bronze.pib_internacional_indicador`` (tabela unificada para a modelagem dbt)
  - ``bronze.pib_<pais>_indicador`` (tabelas individuais por país)

Utiliza ``common.bronze.carregar_duckdb``, sem dependência de scripts DDL manuais,
criando o schema ``bronze`` e espelhando os esquemas PyArrow do Delta Lake.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterable
from pathlib import Path

import duckdb
import pyarrow as pa
from deltalake import DeltaTable

from inflatrack.bronze import pib_internacional
from inflatrack.common import bronze

logger = logging.getLogger("inflatrack.load_pib_internacional")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
PARQUET_BASE_PADRAO = Path("data/parquet")

TABELA_UNIFICADA = "bronze.pib_internacional_indicador"
CHAVE_UNIFICADA = ("pais_iso3", "indicador", "ano", "valor")
CHAVE_INDIVIDUAL = ("indicador", "ano", "valor")


def carregar_pais(
    conexao: duckdb.DuckDBPyConnection,
    pais: str,
    delta_dir: Path | None = None,
    modo: str = "acrescenta",
) -> int:
    """Espelha a tabela Delta indicador de um país específico em ``bronze.pib_<pais>_indicador``."""
    pais_upper = pais.upper()
    delta_dir = delta_dir or pib_internacional.diretorio_padrao_pais(pais_upper)
    sufixo = pib_internacional.sufixo_pais(pais_upper)

    caminho = bronze.caminho(delta_dir, "indicador")
    if not DeltaTable.is_deltatable(caminho):
        raise FileNotFoundError(f"Tabela Delta não encontrada em {caminho}")

    tabela_duckdb = f"bronze.pib_{sufixo}_indicador"
    origem = DeltaTable(caminho).to_pyarrow_table()

    conexao.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    linhas = bronze.carregar_duckdb(conexao, origem, tabela_duckdb, modo, CHAVE_INDIVIDUAL)
    logger.info(
        "Carga concluída para %s em %s: %d linhas inseridas",
        pais_upper,
        tabela_duckdb,
        linhas,
    )
    return linhas


def carregar_unificado(
    conexao: duckdb.DuckDBPyConnection,
    parquet_base: Path = PARQUET_BASE_PADRAO,
    paises: Iterable[str] = pib_internacional.PAISES_PADRAO,
    modo: str = "acrescenta",
) -> int:
    """Espelha dados Delta de todos os países em ``bronze.pib_internacional_indicador``."""
    tabelas_arrow: list[pa.Table] = []

    for p in paises:
        sufixo = pib_internacional.sufixo_pais(p)
        caminho = bronze.caminho(parquet_base / f"pib_{sufixo}", "indicador")
        if DeltaTable.is_deltatable(caminho):
            tabelas_arrow.append(DeltaTable(caminho).to_pyarrow_table())
        else:
            logger.warning("Tabela Delta de %s não encontrada em %s (ignorando)", p, caminho)

    if not tabelas_arrow:
        raise FileNotFoundError("Nenhuma tabela Delta de PIB internacional encontrada para carga.")

    origem_unificada = pa.concat_tables(tabelas_arrow)
    conexao.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    linhas = bronze.carregar_duckdb(
        conexao,
        origem_unificada,
        TABELA_UNIFICADA,
        modo,
        CHAVE_UNIFICADA,
    )
    logger.info("Carga unificada concluída em %s: %d linhas inseridas", TABELA_UNIFICADA, linhas)
    return linhas


def carregar_tudo(
    conexao: duckdb.DuckDBPyConnection,
    parquet_base: Path = PARQUET_BASE_PADRAO,
    paises: Iterable[str] = pib_internacional.PAISES_PADRAO,
    modo: str = "acrescenta",
) -> dict[str, int]:
    """Executa a carga individual de cada país e a carga unificada."""
    resultados = {}
    for p in paises:
        caminho_pais = parquet_base / f"pib_{pib_internacional.sufixo_pais(p)}"
        if (caminho_pais / "indicador").exists():
            resultados[p] = carregar_pais(conexao, p, delta_dir=caminho_pais, modo=modo)
    resultados["unificado"] = carregar_unificado(
        conexao, parquet_base=parquet_base, paises=paises, modo=modo
    )
    return resultados


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PADRAO), help="Caminho do banco DuckDB")
    parser.add_argument(
        "--parquet-base", default=str(PARQUET_BASE_PADRAO), help="Diretório base dos Parquets"
    )
    parser.add_argument(
        "--pais",
        default="todos",
        choices=["todos", "CHN", "USA", "RUS", "chn", "usa", "rus"],
        help="País a carregar (CHN, USA, RUS ou todos)",
    )
    parser.add_argument(
        "--modo",
        default="acrescenta",
        choices=["acrescenta", "substitui"],
        help="Modo de carga no DuckDB",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(db)) as conexao:
        if args.pais.upper() == "TODOS":
            carregar_unificado(conexao, parquet_base=Path(args.parquet_base), modo=args.modo)
        else:
            carregar_pais(conexao, args.pais.upper(), modo=args.modo)

    return 0


if __name__ == "__main__":
    sys.exit(main())
