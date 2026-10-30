"""Carga do Parquet das Contas Nacionais Trimestrais para o DuckDB.

Uso::

    uv run python -m inflatrack.load_pib

Vai para o **mesmo** ``data/duckdb/inflatrack.duckdb`` das commodities, em
tabelas próprias (``pib_setor``, ``pib_valor``). O racional está no cabeçalho
de ``scripts/setup_duckdb_pib.sql``: a pergunta do projeto cruza fontes, e
cruzar dentro de um arquivo é JOIN; entre arquivos, ATTACH em toda sessão.

Idempotente: UPSERT por ``(codigo_setor, data_referencia)``. Revisão do IBGE
em trimestre antigo sobrescreve o valor, que é o comportamento certo — a série
revisada é a série oficial.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

logger = logging.getLogger("inflatrack.load_pib")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
PARQUET_DIR_PADRAO = Path("data/parquet/pib")
SCHEMA_SQL = Path("scripts/setup_duckdb_pib.sql")


def aplicar_esquema(conexao: duckdb.DuckDBPyConnection, caminho: Path) -> None:
    """Cria tabelas e views do PIB. Só usa CREATE IF NOT EXISTS / OR REPLACE."""
    conexao.execute(caminho.read_text(encoding="utf-8"))


def carregar(conexao: duckdb.DuckDBPyConnection, parquet_dir: Path) -> int:
    padrao = str(parquet_dir / "*.parquet").replace("\\", "/")

    total = conexao.execute("SELECT count(*) FROM read_parquet(?)", [padrao]).fetchone()[0]
    logger.info("%d linhas em %s", total, padrao)
    if not total:
        return 0

    # A dimensão nasce do próprio Parquet: nome e grupo vêm dos metadados do
    # SIDRA na ingestão, então renomear um setor na origem se propaga sozinho.
    conexao.execute(
        f"""
        INSERT INTO pib_setor (codigo, nome, grupo, nucleo)
        SELECT DISTINCT ON (codigo_setor) codigo_setor, setor, grupo, nucleo
        FROM read_parquet('{padrao}')
        ORDER BY codigo_setor, data_referencia DESC
        ON CONFLICT (codigo) DO UPDATE SET
            nome = EXCLUDED.nome,
            grupo = EXCLUDED.grupo,
            nucleo = EXCLUDED.nucleo
        """
    )

    conexao.execute(
        f"""
        INSERT INTO pib_valor (codigo_setor, data_referencia, ano, trimestre, valor_milhoes_brl)
        SELECT codigo_setor, data_referencia, ano, trimestre, valor_milhoes_brl
        FROM read_parquet('{padrao}')
        ON CONFLICT (codigo_setor, data_referencia) DO UPDATE SET
            valor_milhoes_brl = EXCLUDED.valor_milhoes_brl
        """
    )
    return conexao.execute("SELECT count(*) FROM pib_valor").fetchone()[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PADRAO))
    parser.add_argument("--parquet-dir", default=str(PARQUET_DIR_PADRAO))
    parser.add_argument("--schema", default=str(SCHEMA_SQL))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parquet_dir = Path(args.parquet_dir)
    if not any(parquet_dir.glob("*.parquet")):
        logger.error("nenhum Parquet em %s — rode `just pib-ingest` antes", parquet_dir)
        return 1

    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    logger.info("conectando em %s", db)
    with duckdb.connect(str(db)) as conexao:
        aplicar_esquema(conexao, Path(args.schema))
        linhas = carregar(conexao, parquet_dir)
        setores = conexao.execute("SELECT count(*) FROM pib_setor").fetchone()[0]
    logger.info("carga concluída: %d setores, %d observações em pib_valor", setores, linhas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
