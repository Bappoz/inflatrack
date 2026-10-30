"""Carga da Bronze Delta do PIB (SIDRA 1846) no DuckDB analítico compartilhado.

A tabela Delta ``data/parquet/pib/valor/`` é espelhada em ``bronze.pib_valor``, sem
nenhuma regra de negócio. A tabela é criada na primeira carga com o esquema do próprio
Delta (``bronze.carregar_duckdb``), então não depende de nenhum ``setup_duckdb_*.sql``.

Só acrescenta, como o Delta: cada divulgação do IBGE revisa trimestres anteriores, e a
revisão chega como linha nova (o valor está na chave). Escolher a versão mais recente é
trabalho da Silver (``stg_pib__valor``), não da carga.

Uso::

    uv run python -m inflatrack.loaders.load_pib
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
from deltalake import DeltaTable

from inflatrack.bronze import bronze_pib
from inflatrack.common import bronze

logger = logging.getLogger("inflatrack.load_pib")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
DELTA_PADRAO = Path(bronze_pib.DIRETORIO_PADRAO)
TABELA_DUCKDB = "bronze.pib_valor"


def carregar(conexao: duckdb.DuckDBPyConnection, delta_dir: Path) -> int:
    """Espelha a tabela Delta ``valor`` em ``bronze.pib_valor``. Devolve linhas inseridas."""
    caminho = bronze.caminho(delta_dir, bronze_pib.TABELA)
    if not DeltaTable.is_deltatable(caminho):
        raise FileNotFoundError(f"Tabela Delta do PIB não encontrada em {caminho}")

    origem = DeltaTable(caminho).to_pyarrow_table()
    conexao.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    return bronze.carregar_duckdb(conexao, origem, TABELA_DUCKDB, "acrescenta", bronze_pib.CHAVE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PADRAO), help="Caminho do banco DuckDB")
    parser.add_argument(
        "--delta-dir", default=str(DELTA_PADRAO), help="Diretório da Bronze Delta do PIB"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)

    try:
        with duckdb.connect(str(db)) as conexao:
            novas = carregar(conexao, Path(args.delta_dir))
            total = conexao.execute(f"SELECT count(*) FROM {TABELA_DUCKDB}").fetchone()[0]
    except FileNotFoundError as erro:
        logger.error("%s — rode `just bronze-pib` antes", erro)
        return 1
    logger.info("%s: %d linhas novas, %d no total", TABELA_DUCKDB, novas, total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
