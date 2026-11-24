"""Ativos da fonte ENSO (El Niño / La Niña): o RONI do NOAA."""

from dagster import AssetExecutionContext, asset

from inflatrack.bronze import enso
from inflatrack.loaders import load_enso
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar


@asset(
    group_name="enso",
    retry_policy=RETRY_REDE,
    kinds={"python", "delta"},
    description="RONI (NOAA/CPC) inteiro, desde 1950, em enso_resposta e enso_roni (Delta).",
)
def enso_parquet(context: AssetExecutionContext) -> None:
    executar(context, enso.main, "coletar")


@asset(
    group_name="enso",
    deps=[enso_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Carga do RONI no DuckDB (bronze.enso_roni).",
)
def enso_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_enso.main)
