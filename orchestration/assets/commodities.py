"""Ativos da fonte `commodities`: Alpha Vantage → Bronze em Delta → DuckDB.

Modelo para os módulos das outras fontes: um arquivo por fonte em `orchestration/assets/`,
carregado sozinho por `orchestration/definitions.py`.
"""

from dagster import AssetExecutionContext, asset

from inflatrack import load_commodities
from inflatrack.bronze import commodities
from orchestration.assets.comum import POOL_DUCKDB, executar


@asset(
    group_name="commodities",
    kinds={"python", "delta"},
    description="Cotações das 9 commodities (Bronze em Delta). Sem retry: cota de 25 req./dia.",
)
def commodities_parquet(context: AssetExecutionContext) -> None:
    # Cota esgotada, série vazia ou checagem reprovada fazem o ingestor sair com erro.
    executar(context, commodities.main, "--commodity", "ALL")


@asset(
    group_name="commodities",
    deps=[commodities_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Espelha o Delta das cotações em bronze.commodities_cotacao no DuckDB.",
)
def commodities_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_commodities.main)
