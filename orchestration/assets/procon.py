"""Ativos da fonte Cesta Básica do PROCON: ingestão Raw/Delta/Parquet e carga no DuckDB."""

from collections.abc import Callable

from dagster import (
    AssetExecutionContext,
    Backoff,
    Failure,
    RetryPolicy,
    asset,
)

from inflatrack.bronze import ingest_procon
from inflatrack.loaders import load_procon

POOL_DUCKDB = "duckdb_writer"
RETRY_REDE = RetryPolicy(max_retries=2, delay=30, backoff=Backoff.EXPONENTIAL)


def _executar(context: AssetExecutionContext, main: Callable[..., int], *argv: str) -> None:
    context.log.info("%s %s", main.__module__, " ".join(argv))
    codigo = main(list(argv))
    if codigo not in (0, None):
        raise Failure(f"{main.__module__} terminou com código {codigo}")


@asset(
    group_name="procon",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet", "delta"},
    description="Cesta básica do PROCON: Raw compactado e Bronze Delta.",
)
def procon_parquet(context: AssetExecutionContext) -> None:
    _executar(context, ingest_procon.main)


@asset(
    group_name="procon",
    deps=[procon_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Carga da Cesta Básica do PROCON no DuckDB (bronze.procon_cesta_basica).",
)
def procon_duckdb(context: AssetExecutionContext) -> None:
    _executar(context, load_procon.main)
