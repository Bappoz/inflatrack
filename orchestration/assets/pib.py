"""Ativos da fonte `pib`: SIDRA 1846 → Bronze em Delta e Parquet → DuckDB.

Modelo para os módulos das outras fontes: um arquivo por fonte em `orchestration/assets/`,
carregado sozinho por `orchestration/definitions.py`.
"""

from dagster import AssetExecutionContext, asset

from inflatrack import ingest_pib, load_pib
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar


@asset(
    group_name="pib",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet"},
    description="Contas nacionais trimestrais (SIDRA 1846), 1996 até hoje.",
)
def pib_parquet(context: AssetExecutionContext) -> None:
    executar(context, ingest_pib.main)


@asset(group_name="pib", deps=[pib_parquet], pool=POOL_DUCKDB, kinds={"python", "duckdb"})
def pib_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_pib.main)
