"""Ativos da fonte Salário Mínimo (DIEESE): ingestão Raw/Delta/Parquet e carga no DuckDB."""

from collections.abc import Callable

from dagster import (
    AssetExecutionContext,
    Backoff,
    Failure,
    RetryPolicy,
    asset,
)

from inflatrack import ingest_salario_minimo, load_salario_minimo

POOL_DUCKDB = "duckdb_writer"
RETRY_REDE = RetryPolicy(max_retries=2, delay=30, backoff=Backoff.EXPONENTIAL)


def _executar(context: AssetExecutionContext, main: Callable[..., int], *argv: str) -> None:
    context.log.info("%s %s", main.__module__, " ".join(argv))
    codigo = main(list(argv))
    if codigo != 0:
        raise Failure(f"{main.__module__} terminou com código {codigo}")


@asset(
    group_name="dieese",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet", "delta"},
    description="Salário mínimo do DIEESE: Raw, Parquet e Bronze Delta.",
)
def salario_minimo_parquet(context: AssetExecutionContext) -> None:
    _executar(context, ingest_salario_minimo.main)


@asset(
    group_name="dieese",
    deps=[salario_minimo_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Carga de salário mínimo no DuckDB (bronze.salario_minimo_mes e tabelas legadas).",
)
def salario_minimo_duckdb(context: AssetExecutionContext) -> None:
    _executar(context, load_salario_minimo.main)
