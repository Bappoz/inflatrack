"""Ativos da fonte PIB Internacional (China, EUA e Rússia): Banco Mundial -> Delta -> DuckDB."""

from dagster import AssetExecutionContext, asset

from inflatrack import (
    load_pib_internacional,
    pib_internacional,
)
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar

# --- Coletas Bronze (Delta Lake) por país ---


@asset(
    group_name="pib_internacional",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet", "delta"},
    description="Crescimento e PIB em US$ da China (Banco Mundial), anual.",
)
def pib_china_parquet(context: AssetExecutionContext) -> None:
    executar(context, pib_internacional.main, "coletar", "--pais", "CHN")


@asset(
    group_name="pib_internacional",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet", "delta"},
    description="Crescimento e PIB em US$ dos EUA (Banco Mundial), anual.",
)
def pib_usa_parquet(context: AssetExecutionContext) -> None:
    executar(context, pib_internacional.main, "coletar", "--pais", "USA")


@asset(
    group_name="pib_internacional",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet", "delta"},
    description="Crescimento e PIB em US$ da Rússia (Banco Mundial), anual.",
)
def pib_russia_parquet(context: AssetExecutionContext) -> None:
    executar(context, pib_internacional.main, "coletar", "--pais", "RUS")


# --- Carga Centralizada no DuckDB ---


@asset(
    group_name="pib_internacional",
    deps=[pib_china_parquet, pib_usa_parquet, pib_russia_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Carga centralizada de China, EUA e Rússia em bronze.pib_internacional_indicador.",
)
def pib_internacional_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_pib_internacional.main, "--pais", "todos")
