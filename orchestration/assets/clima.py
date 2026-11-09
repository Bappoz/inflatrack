"""Ativos da fonte Dados do Clima (INMET): catálogo de estações e medições."""

from collections.abc import Callable

from dagster import (
    Array,
    AssetExecutionContext,
    Backoff,
    Failure,
    RetryPolicy,
    String,
    asset,
)

from inflatrack import ingest_clima, load_clima

POOL_DUCKDB = "duckdb_writer"
RETRY_REDE = RetryPolicy(max_retries=2, delay=30, backoff=Backoff.EXPONENTIAL)


def _executar(context: AssetExecutionContext, main: Callable[..., int], *argv: str) -> None:
    context.log.info("%s %s", main.__module__, " ".join(argv))
    codigo = main(list(argv))
    if codigo != 0:
        raise Failure(f"{main.__module__} terminou com código {codigo}")


@asset(
    group_name="clima",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet", "delta"},
    description="Cadastro das estações meteorológicas do INMET em Raw, Parquet e Bronze Delta.",
)
def clima_parquet(context: AssetExecutionContext) -> None:
    _executar(context, ingest_clima.main, "--apenas-estacoes")


@asset(
    group_name="clima",
    deps=[clima_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description=(
        "Carga do catálogo de estações no DuckDB (bronze.clima_estacao e tabelas legadas)."
    ),
)
def clima_duckdb(context: AssetExecutionContext) -> None:
    _executar(context, load_clima.main)


@asset(
    group_name="clima_medicoes",
    deps=[clima_parquet],
    retry_policy=RETRY_REDE,
    kinds={"python", "delta"},
    config_schema={
        "estacoes": Array(String),
        "data_inicio": String,
        "data_fim": String,
    },
    description=(
        "Coleta diária manual do INMET. Exige IDs de estação e intervalo explícitos; "
        "não participa do job diário de catálogo."
    ),
)
def clima_medicoes(context: AssetExecutionContext) -> None:
    config = context.op_config
    argumentos = [
        "--medicoes",
        "--de",
        config["data_inicio"],
        "--ate",
        config["data_fim"],
    ]
    for estacao in config["estacoes"]:
        argumentos.extend(("--estacao", estacao))
    _executar(context, ingest_clima.main, *argumentos)


@asset(
    group_name="clima_medicoes",
    deps=[clima_medicoes],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Promove as medições diárias do Delta para bronze.clima_medicao.",
)
def clima_medicoes_duckdb(context: AssetExecutionContext) -> None:
    _executar(context, load_clima.main)
