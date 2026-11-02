"""Ativos da fonte PIB Internacional (China, EUA e Rússia): Banco Mundial -> Delta -> DuckDB."""

from dagster import AssetExecutionContext, asset

from inflatrack import (
    bronze_pib_china,
    bronze_pib_russia,
    bronze_pib_usa,
    load_pib_china,
    load_pib_internacional,
)
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar

# --- China ---


@asset(
    group_name="pib_china",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet", "delta"},
    description="Crescimento e PIB em US$ da China (Banco Mundial), anual.",
)
def pib_china_parquet(context: AssetExecutionContext) -> None:
    executar(context, bronze_pib_china.main, "coletar")


@asset(
    group_name="pib_china",
    deps=[pib_china_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Carga do PIB da China no DuckDB analítico.",
)
def pib_china_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_pib_china.main, "--pais", "CHN")


# --- Estados Unidos ---


@asset(
    group_name="pib_internacional",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet", "delta"},
    description="Crescimento e PIB em US$ dos EUA (Banco Mundial), anual.",
)
def pib_usa_parquet(context: AssetExecutionContext) -> None:
    executar(context, bronze_pib_usa.main, "coletar")


@asset(
    group_name="pib_internacional",
    deps=[pib_usa_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Carga do PIB dos EUA no DuckDB analítico.",
)
def pib_usa_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_pib_internacional.main, "--pais", "USA")


# --- Rússia ---


@asset(
    group_name="pib_internacional",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet", "delta"},
    description="Crescimento e PIB em US$ da Rússia (Banco Mundial), anual.",
)
def pib_russia_parquet(context: AssetExecutionContext) -> None:
    executar(context, bronze_pib_russia.main, "coletar")


@asset(
    group_name="pib_internacional",
    deps=[pib_russia_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Carga do PIB da Rússia no DuckDB analítico.",
)
def pib_russia_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_pib_internacional.main, "--pais", "RUS")


# --- Unificado ---


@asset(
    group_name="pib_internacional",
    deps=[pib_china_parquet, pib_usa_parquet, pib_russia_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Carga unificada de China, EUA e Rússia em bronze.pib_internacional_indicador.",
)
def pib_internacional_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_pib_internacional.main, "--pais", "todos")
