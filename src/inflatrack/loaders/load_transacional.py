"""Carga da Bronze Delta do CDC no DuckDB: ``bronze.transacional_mudanca``.

Espelha ``data/parquet/transacional/mudanca/`` sem regra de negócio, e só acrescenta: rodar de
novo não duplica. Sem Delta (ninguém rodou o CDC ainda nesta máquina), cria a tabela vazia, com
o esquema do CDC, para o ``dbt build`` dos colegas não depender do Postgres: os modelos do
lojista apenas ficam vazios.

Uso::

    uv run python -m inflatrack.loaders.load_transacional
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
from deltalake import DeltaTable

from inflatrack.cdc import transacional
from inflatrack.common import bronze
from inflatrack.common.db import DUCKDB_PADRAO

logger = logging.getLogger("inflatrack.load_transacional")

DELTA_PADRAO = Path(transacional.DIRETORIO_PADRAO)
TABELA_DUCKDB = "bronze.transacional_mudanca"


def carregar(conexao: duckdb.DuckDBPyConnection, delta_dir: Path) -> int:
    """Espelha o Delta do CDC no DuckDB. Devolve as linhas inseridas."""
    conexao.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    caminho = bronze.caminho(delta_dir, transacional.TABELA_DELTA)
    if DeltaTable.is_deltatable(caminho):
        origem = DeltaTable(caminho).to_pyarrow_table()
    else:
        logger.warning("%s ainda não existe: %s fica vazia", caminho, TABELA_DUCKDB)
        origem = transacional.ESQUEMA_MUDANCA.empty_table()
    return bronze.carregar_duckdb(
        conexao, origem, TABELA_DUCKDB, "acrescenta", transacional.CHAVE_MUDANCA
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=str(DUCKDB_PADRAO), help="Caminho do banco DuckDB")
    parser.add_argument("--delta-dir", default=str(DELTA_PADRAO), help="Diretório do Delta do CDC")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(db)) as conexao:
        novas = carregar(conexao, Path(args.delta_dir))
        total = conexao.execute(f"SELECT count(*) FROM {TABELA_DUCKDB}").fetchone()[0]
    logger.info("%s: %d linhas novas, %d no total", TABELA_DUCKDB, novas, total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
