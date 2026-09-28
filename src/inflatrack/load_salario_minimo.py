"""Carga do Parquet de Salário Mínimo (DIEESE) no DuckDB analítico compartilhado."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

logger = logging.getLogger("inflatrack.load_salario_minimo")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
PARQUET_PADRAO = Path("data/parquet/dieese/salario_minimo.parquet")
SCHEMA_SQL = Path(__file__).resolve().parents[2] / "scripts" / "setup_duckdb_salario_minimo.sql"


def carregar(conexao: duckdb.DuckDBPyConnection, parquet: Path) -> int:
    """Aplica o esquema DDL e faz UPSERT idempotente por ano_mes."""
    conexao.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    conexao.execute(
        """
        INSERT INTO salario_minimo (
            ano_mes,
            data_referencia,
            ano,
            mes,
            salario_nominal,
            salario_necessario,
            multiplo_necessario_nominal,
            atualizado_em
        )
        SELECT
            ano_mes,
            data_referencia,
            ano,
            mes,
            salario_nominal,
            salario_necessario,
            multiplo_necessario_nominal,
            now()
        FROM read_parquet(?)
        ON CONFLICT (ano_mes) DO UPDATE SET
            data_referencia = EXCLUDED.data_referencia,
            ano = EXCLUDED.ano,
            mes = EXCLUDED.mes,
            salario_nominal = EXCLUDED.salario_nominal,
            salario_necessario = EXCLUDED.salario_necessario,
            multiplo_necessario_nominal = EXCLUDED.multiplo_necessario_nominal,
            atualizado_em = now()
        """,
        [str(parquet)],
    )
    return conexao.execute("SELECT count(*) FROM salario_minimo").fetchone()[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PADRAO), help="Caminho do banco DuckDB")
    parser.add_argument("--parquet", default=str(PARQUET_PADRAO), help="Caminho do arquivo Parquet")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parquet = Path(args.parquet)
    if not parquet.is_file():
        logger.error(
            "Parquet não encontrado em %s — execute a ingestão antes (`ingest_salario_minimo`)",
            parquet,
        )
        return 1

    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db)) as conexao:
        total = carregar(conexao, parquet)
    logger.info("Carga concluída com sucesso: %d meses registrados em salario_minimo", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
