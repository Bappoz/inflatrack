"""Conexões padronizadas: o DSN do Postgres e o caminho do DuckDB analítico único (ADR 0002)."""

from __future__ import annotations

import os
from pathlib import Path

DUCKDB_PADRAO = Path("data/duckdb/inflatrack.duckdb")


def dsn_do_ambiente() -> str:
    """Monta o DSN a partir do .env / variáveis de ambiente."""
    usuario = os.environ.get("POSTGRES_USER", "inflatrack")
    senha = os.environ.get("POSTGRES_PASSWORD", "inflatrack")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    porta = os.environ.get("POSTGRES_PORT", "5432")
    banco = os.environ.get("POSTGRES_DB", "inflatrack")
    return f"postgresql://{usuario}:{senha}@{host}:{porta}/{banco}"
