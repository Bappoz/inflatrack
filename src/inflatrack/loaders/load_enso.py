"""Carga do RONI (ENSO) do Delta em bronze.enso_roni, no DuckDB analítico compartilhado."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
from deltalake import DeltaTable

logger = logging.getLogger("inflatrack.load_enso")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
DELTA_PADRAO = Path("data/parquet/enso")
SCHEMA_SQL = Path(__file__).resolve().parents[3] / "scripts" / "sql" / "setup_duckdb_enso.sql"
COLUNAS = (
    "id_leitura, temporada, ano, mes_referencia, roni, "
    "_id_resposta, _fonte, _requisicao, _ingerido_em"
)


def carregar_bronze_roni(conexao: duckdb.DuckDBPyConnection, delta_dir: Path) -> int:
    """Substitui bronze.enso_roni pelo conteúdo do Delta, numa transação."""
    caminho = delta_dir / "roni"
    if not DeltaTable.is_deltatable(str(caminho)):
        raise FileNotFoundError(f"Tabela Delta do RONI não encontrada em {caminho}")
    conexao.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    conexao.register("temp_enso_roni", DeltaTable(str(caminho)).to_pyarrow_table())
    conexao.begin()
    conexao.execute("DELETE FROM bronze.enso_roni")
    conexao.execute(
        f"INSERT INTO bronze.enso_roni ({COLUNAS}) SELECT {COLUNAS} FROM temp_enso_roni"
    )
    conexao.commit()
    conexao.unregister("temp_enso_roni")
    return conexao.execute("SELECT count(*) FROM bronze.enso_roni").fetchone()[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PADRAO))
    parser.add_argument("--delta-dir", default=str(DELTA_PADRAO))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db)) as conexao:
        # A tabela existe mesmo sem Delta: o dbt lê bronze.enso_roni.
        conexao.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        try:
            total = carregar_bronze_roni(conexao, Path(args.delta_dir))
        except FileNotFoundError as erro:
            logger.error("%s", erro)
            return 1
    logger.info("RONI carregado: %d linhas em bronze.enso_roni", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
