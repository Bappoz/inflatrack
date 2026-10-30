"""Copia tabelas da Gold (DuckDB) para o schema `serie` do PostgreSQL, a vitrine do painel.

O DuckDB calcula e o Postgres serve. O Metabase lê **só** o Postgres: com uma conexão do
Metabase aberta no arquivo do DuckDB, nem o dbt nem os loaders conseguem escrever (o DuckDB
aceita um escritor por vez, testado em 2026-10-30). Esta cópia é a ponte entre os dois.

Regras:

* Copia só o que está em ``TABELAS``: ``gold.<nome>`` vira ``serie.<nome>``. Para o painel
  enxergar uma tabela nova da Gold, acrescente o nome aqui (PLAN_E3_E4.md, Seção 5).
* Na primeira vez, a tabela é criada com as colunas da Gold. Depois, cada cópia apaga as
  linhas e insere de novo, **sem recriar a tabela**: índices, permissões e RLS criados por
  migration em ``serie`` continuam valendo.
* Todas as tabelas vão numa transação só do Postgres: o painel nunca vê metade de uma carga.
  Se a estrutura de uma tabela da Gold mudar, a cópia falha e nada é alterado; ajuste a
  migration (ou apague a tabela em ``serie`` para ela ser recriada).
* O Postgres não calcula nada: só recebe o que o dbt calculou (Seção 1.1).

Uso::

    uv run python -m inflatrack.reverse_etl.exportar_serie
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
from dotenv import load_dotenv

from inflatrack.bronze.ingest import dsn_do_ambiente

logger = logging.getLogger("inflatrack.exportar_serie")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
SCHEMA_DESTINO = "serie"

# Tabelas da Gold que o painel enxerga. Cada integrante acrescenta as suas.
TABELAS: tuple[str, ...] = ("dim_calendario",)


def _colunas(conexao: duckdb.DuckDBPyConnection, catalogo: str, schema: str, tabela: str):
    return conexao.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_catalog = ? AND table_schema = ? AND table_name = ? "
        "ORDER BY ordinal_position",
        [catalogo, schema, tabela],
    ).fetchall()


def exportar(
    conexao: duckdb.DuckDBPyConnection,
    tabelas: tuple[str, ...] = TABELAS,
    schema: str = SCHEMA_DESTINO,
) -> dict[str, int]:
    """Copia ``dk.gold.<t>`` para ``pg.<schema>.<t>``. A conexão já tem ``dk`` e ``pg`` anexados.

    Devolve as linhas copiadas por tabela.
    """
    for tabela in tabelas:
        if not _colunas(conexao, "dk", "gold", tabela):
            raise ValueError(f"gold.{tabela} não existe no DuckDB: rode o dbt antes")

    conexao.execute(f"CREATE SCHEMA IF NOT EXISTS pg.{schema}")
    copiadas: dict[str, int] = {}
    conexao.execute("BEGIN")
    try:
        for tabela in tabelas:
            origem, destino = f"dk.gold.{tabela}", f"pg.{schema}.{tabela}"
            existente = _colunas(conexao, "pg", schema, tabela)
            if not existente:
                conexao.execute(f"CREATE TABLE {destino} AS SELECT * FROM {origem}")
            elif existente != _colunas(conexao, "dk", "gold", tabela):
                raise ValueError(
                    f"{schema}.{tabela} tem colunas diferentes de gold.{tabela}: ajuste a "
                    f"migration ou apague a tabela no Postgres para ela ser recriada"
                )
            else:
                conexao.execute(f"DELETE FROM {destino}")
                conexao.execute(f"INSERT INTO {destino} SELECT * FROM {origem}")
            copiadas[tabela] = conexao.execute(f"SELECT count(*) FROM {origem}").fetchone()[0]
        conexao.execute("COMMIT")
    except Exception:
        conexao.execute("ROLLBACK")
        raise
    return copiadas


def conectar(db: Path, dsn: str) -> duckdb.DuckDBPyConnection:
    """Conexão em memória com o DuckDB analítico (só leitura) e o Postgres anexados."""
    conexao = duckdb.connect()
    conexao.execute("INSTALL postgres; LOAD postgres;")
    conexao.execute(f"ATTACH '{db.as_posix()}' AS dk (READ_ONLY)")
    # ATTACH não aceita parâmetro: o DSN entra como literal, com aspas escapadas.
    dsn_literal = dsn.replace("'", "''")
    conexao.execute(f"ATTACH '{dsn_literal}' AS pg (TYPE postgres)")
    return conexao


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(DB_PADRAO))
    parser.add_argument("--dsn", default=None, help="padrão: montado do .env")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    db = Path(args.db)
    if not db.exists():
        logger.error("%s não existe: rode os loaders e o dbt antes", db)
        return 1
    try:
        with conectar(db, args.dsn or dsn_do_ambiente()) as conexao:
            copiadas = exportar(conexao)
    except (duckdb.Error, ValueError) as erro:
        logger.error("cópia para o Postgres interrompida, nada foi alterado: %s", erro)
        return 1
    for tabela, linhas in copiadas.items():
        logger.info("%s.%s: %d linhas", SCHEMA_DESTINO, tabela, linhas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
