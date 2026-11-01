"""Ativos da fonte Taxa Selic (SGS/BACEN): API → Delta Lake → DuckDB."""

from dagster import AssetExecutionContext, asset

from inflatrack.bronze import selic
from inflatrack.loaders import load_selic
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar


@asset(
    group_name="macro",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet", "delta"},
    description="Taxa Selic diária (SGS série 11), salva em Delta Lake.",
)
def selic_parquet(context: AssetExecutionContext) -> None:
    executar(context, selic.main)


@asset(
    group_name="macro",
    deps=[selic_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Espelha a tabela Delta da Selic em bronze.selic_taxa no DuckDB.",
)
def selic_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_selic.main)
