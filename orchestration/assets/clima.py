"""Ativos da fonte Dados do Clima (INMET): catálogo de estações e medições."""

from dagster import (
    Array,
    AssetExecutionContext,
    Field,
    String,
    asset,
)

from inflatrack import ingest_clima, load_clima
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar


@asset(
    group_name="clima",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet", "delta"},
    description="Cadastro das estações meteorológicas do INMET em Raw, Parquet e Bronze Delta.",
)
def clima_parquet(context: AssetExecutionContext) -> None:
    executar(context, ingest_clima.main, "--apenas-estacoes")


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
    executar(context, load_clima.main)


@asset(
    group_name="clima",
    deps=[clima_parquet],
    retry_policy=RETRY_REDE,
    kinds={"python", "delta"},
    config_schema={
        "estacoes": Field(Array(String), default_value=[]),
        "data_inicio": Field(String, is_required=False),
        "data_fim": Field(String, is_required=False),
    },
    description=(
        "Coleta as estações mapeadas nos últimos 7 dias completos. "
        "Estações e intervalo podem ser sobrescritos para carga histórica."
    ),
)
def clima_medicoes(context: AssetExecutionContext) -> None:
    config = context.op_execution_context.op_config
    argumentos = ["--medicoes"]
    if "data_inicio" in config:
        argumentos.extend(("--de", config["data_inicio"]))
    if "data_fim" in config:
        argumentos.extend(("--ate", config["data_fim"]))
    for estacao in config["estacoes"]:
        argumentos.extend(("--estacao", estacao))
    executar(context, ingest_clima.main, *argumentos)


@asset(
    group_name="clima",
    deps=[clima_medicoes, clima_duckdb],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Promove as medições diárias do Delta para bronze.clima_medicao.",
)
def clima_medicoes_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_clima.main)
