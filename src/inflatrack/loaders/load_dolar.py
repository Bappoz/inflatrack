"""Carga da Bronze Delta do Dólar Comercial no DuckDB analítico compartilhado.

A tabela Delta ``data/parquet/dolar/boletim/`` é espelhada em ``bronze.dolar_boletim``,
sem nenhuma regra de negócio. A tabela é criada na primeira carga com o esquema do próprio
Delta (``bronze.carregar_duckdb``), não dependendo de nenhum script SQL manual.

* ``acrescenta`` (padrão): insere apenas os boletins novos ou atualizados.
* ``substitui``: substitui partições ou registros existentes.

Uso::

    uv run python -m inflatrack.loaders.load_dolar
    uv run python -m inflatrack.loaders.load_dolar --modo acrescenta
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
from deltalake import DeltaTable

from inflatrack.bronze import dolar
from inflatrack.common import bronze

logger = logging.getLogger("inflatrack.load_dolar")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
DELTA_PADRAO = Path(dolar.DIRETORIO_PADRAO)
TABELA_DELTA = dolar.TABELA  # "boletim"
TABELA_DUCKDB = "bronze.dolar_boletim"

COLUNAS_POR_MODO = {
    "substitui": ("ano",),
    "acrescenta": dolar.CHAVE_BOLETIM,
}


def carregar_bronze(
    conexao: duckdb.DuckDBPyConnection,
    delta_dir: Path,
    modo: str = "acrescenta",
) -> int:
    """Espelha a tabela Delta ``boletim`` em ``bronze.dolar_boletim``. Devolve linhas novas."""
    if modo not in COLUNAS_POR_MODO:
        raise ValueError(f"modo inválido: {modo!r}. Escolha entre {list(COLUNAS_POR_MODO)}")

    caminho = bronze.caminho(delta_dir, TABELA_DELTA)
    if not DeltaTable.is_deltatable(caminho):
        raise FileNotFoundError(f"Tabela Delta do Dólar não encontrada em {caminho}")

    origem = DeltaTable(caminho).to_pyarrow_table()
    conexao.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    return bronze.carregar_duckdb(conexao, origem, TABELA_DUCKDB, modo, COLUNAS_POR_MODO[modo])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PADRAO), help="Caminho do banco DuckDB")
    parser.add_argument(
        "--delta-dir", default=str(DELTA_PADRAO), help="Diretório da Bronze Delta do Dólar"
    )
    parser.add_argument(
        "--modo",
        choices=list(COLUNAS_POR_MODO),
        default="acrescenta",
        help="Como tratar registros existentes (padrão: acrescenta)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)

    try:
        with duckdb.connect(str(db)) as conexao:
            novas = carregar_bronze(conexao, Path(args.delta_dir), modo=args.modo)
            total = conexao.execute(f"SELECT count(*) FROM {TABELA_DUCKDB}").fetchone()[0]
    except FileNotFoundError as erro:
        logger.error("%s — rode `uv run python -m inflatrack.bronze.dolar` antes", erro)
        return 1

    logger.info("%s: %d linhas novas (%s), %d no total", TABELA_DUCKDB, novas, args.modo, total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
