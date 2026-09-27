"""Carga do Parquet do PIB da China no DuckDB analítico do InflaTrack."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

logger = logging.getLogger("inflatrack.load_pib_china")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
PARQUET_PADRAO = Path("data/parquet/pib_china/pib_china.parquet")
SCHEMA_SQL = Path(__file__).resolve().parents[2] / "scripts" / "setup_duckdb_pib_china.sql"


def carregar(conexao: duckdb.DuckDBPyConnection, parquet: Path) -> int:
    """Aplica o esquema e faz UPSERT por ano."""
    conexao.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    conexao.execute(
        """
        INSERT INTO pib_china (ano, crescimento_pib_pct, pib_usd)
        SELECT ano, crescimento_pib_pct, pib_usd
        FROM read_parquet(?)
        ON CONFLICT (ano) DO UPDATE SET
            crescimento_pib_pct = EXCLUDED.crescimento_pib_pct,
            pib_usd = EXCLUDED.pib_usd,
            atualizado_em = now()
        """,
        [str(parquet)],
    )
    return conexao.execute("SELECT count(*) FROM pib_china").fetchone()[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PADRAO))
    parser.add_argument("--parquet", default=str(PARQUET_PADRAO))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parquet = Path(args.parquet)
    if not parquet.is_file():
        logger.error("Parquet não encontrado em %s — rode `just pib-china-ingest` antes", parquet)
        return 1

    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db)) as conexao:
        total = carregar(conexao, parquet)
    logger.info("carga concluída: %d anos em pib_china", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
