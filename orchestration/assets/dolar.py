"""Ativos da fonte Dólar Comercial (PTAX/Olinda): API → Delta Lake → DuckDB."""

from dagster import AssetExecutionContext, asset

from inflatrack.bronze import dolar
from inflatrack.loaders import load_dolar
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar


@asset(
    group_name="macro",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet", "delta"},
    description="Cotações do Dólar comercial PTAX diário (Olinda), salvas em Delta Lake.",
)
def dolar_parquet(context: AssetExecutionContext) -> None:
    executar(context, dolar.main)


@asset(
    group_name="macro",
    deps=[dolar_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Espelha a tabela Delta do Dólar em bronze.dolar_boletim no DuckDB.",
)
def dolar_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_dolar.main)
