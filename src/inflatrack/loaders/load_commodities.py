"""Carga da Bronze Delta de Commodities (Alpha Vantage) no DuckDB analítico compartilhado.

A tabela Delta ``data/parquet/commodities/cotacao/`` (particionada por ``symbol``) é
espelhada em ``bronze.commodities_cotacao``, sem nenhuma regra de negócio. A tabela é
criada na primeira carga com o esquema do próprio Delta (``bronze.carregar_duckdb``),
então não depende de nenhum ``setup_duckdb_*.sql``.

* ``substitui`` (padrão): troca as linhas de cada ``symbol`` presente no Delta, como o
  próprio Delta faz a cada coleta (a Alpha Vantage devolve a série inteira).
* ``acrescenta``: insere só as cotações que ainda não estão lá (chave com o preço).

Uso::

    uv run python -m inflatrack.loaders.load_commodities
    uv run python -m inflatrack.loaders.load_commodities --modo acrescenta
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
from deltalake import DeltaTable

from inflatrack.common import bronze

logger = logging.getLogger("inflatrack.load_commodities")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
DELTA_PADRAO = Path("data/parquet/commodities")
TABELA_DELTA = "cotacao"
TABELA_DUCKDB = "bronze.commodities_cotacao"

# Colunas que identificam o que é "a mesma linha" em cada modo de bronze.carregar_duckdb.
COLUNAS_POR_MODO = {
    "substitui": ("symbol",),
    "acrescenta": ("symbol", "data_referencia", "preco"),
}


def carregar_bronze(
    conexao: duckdb.DuckDBPyConnection,
    delta_dir: Path,
    modo: str = "substitui",
) -> int:
    """Espelha a tabela Delta ``cotacao`` em ``bronze.commodities_cotacao``.

    Devolve o total de linhas da tabela no DuckDB depois da carga.
    """
    if modo not in COLUNAS_POR_MODO:
        modos = tuple(COLUNAS_POR_MODO)
        raise ValueError(f"Modo de carga inválido: {modo!r}. Escolha entre {modos}")

    caminho = bronze.caminho(delta_dir, TABELA_DELTA)
    if not DeltaTable.is_deltatable(caminho):
        raise FileNotFoundError(f"Tabela Delta de cotações não encontrada em {caminho}")

    origem = DeltaTable(caminho).to_pyarrow_table()
    conexao.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    inseridas = bronze.carregar_duckdb(conexao, origem, TABELA_DUCKDB, modo, COLUNAS_POR_MODO[modo])
    total = conexao.execute(f"SELECT count(*) FROM {TABELA_DUCKDB}").fetchone()[0]
    logger.info("%s (%s): %d linhas inseridas, %d no total", TABELA_DUCKDB, modo, inseridas, total)
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PADRAO), help="Caminho do banco DuckDB")
    parser.add_argument(
        "--delta-dir", default=str(DELTA_PADRAO), help="Diretório da Bronze Delta de commodities"
    )
    parser.add_argument("--modo", choices=tuple(COLUNAS_POR_MODO), default="substitui")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)

    try:
        with duckdb.connect(str(db)) as conexao:
            carregar_bronze(conexao, Path(args.delta_dir), modo=args.modo)
    except FileNotFoundError as erro:
        logger.error("%s — rode `just bronze-commodities` antes", erro)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
