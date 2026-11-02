"""Carga do Parquet do PIB no DuckDB analítico do InflaTrack.

Suporta a carga legada da China (via ``setup_duckdb_pib_china.sql``) e delega para
``inflatrack.loaders.load_pib_internacional`` para carregar também EUA e Rússia.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

from inflatrack.loaders import load_pib_internacional

logger = logging.getLogger("inflatrack.load_pib_china")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
PARQUET_PADRAO = Path("data/parquet/pib_china/pib_china.parquet")
SCHEMA_SQL = Path(__file__).resolve().parents[3] / "scripts" / "sql" / "setup_duckdb_pib_china.sql"


def carregar(conexao: duckdb.DuckDBPyConnection, parquet: Path) -> int:
    """Aplica o esquema e faz UPSERT por ano na tabela legada pib_china."""
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
    parser.add_argument(
        "--pais",
        default="CHN",
        choices=["CHN", "USA", "RUS", "todos"],
        help="País a carregar no DuckDB",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)

    pais_alvo = args.pais.upper()
    if pais_alvo != "CHN":
        with duckdb.connect(str(db)) as conexao:
            if pais_alvo == "TODOS":
                load_pib_internacional.carregar_tudo(conexao)
            else:
                load_pib_internacional.carregar_pais(conexao, pais_alvo)
        return 0

    parquet = Path(args.parquet)
    if not parquet.is_file():
        logger.error("Parquet não encontrado em %s — rode `just pib-china-ingest` antes", parquet)
        return 1

    with duckdb.connect(str(db)) as conexao:
        total = carregar(conexao, parquet)
    logger.info("carga concluída: %d anos em pib_china", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
