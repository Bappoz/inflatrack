"""Ativos da fonte Dados do Clima (INMET): catálogo de estações e medições diárias (BDMEP)."""

from dagster import Array, AssetExecutionContext, Field, Int, String, asset

from inflatrack import clima, load_clima
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar


@asset(
    group_name="clima",
    retry_policy=RETRY_REDE,
    kinds={"python", "delta"},
    description="Catálogo de estações do INMET (API) em clima_resposta e clima_estacao (Delta).",
)
def clima_parquet(context: AssetExecutionContext) -> None:
    executar(context, clima.main, "coletar", "--apenas-estacoes")


@asset(
    group_name="clima",
    deps=[clima_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Carga do catálogo de estações no DuckDB (bronze.clima_estacao).",
)
def clima_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_clima.main, "--tabela", "estacao")


@asset(
    group_name="clima",
    retry_policy=RETRY_REDE,
    kinds={"python", "delta"},
    config_schema={
        "estacoes": Field(
            Array(String),
            default_value=[],
            description="IDs INMET no lugar do de-para estação -> localidade.",
        ),
        "ano_inicio": Field(Int, is_required=False, description="Padrão: 2006."),
        "ano_fim": Field(Int, is_required=False, description="Padrão: o ano corrente."),
    },
    description=(
        "Medições diárias das estações do de-para a partir dos pacotes anuais do BDMEP. "
        "Só baixa o pacote de um ano quando o INMET o republicou ou o de-para mudou."
    ),
)
def clima_medicoes(context: AssetExecutionContext) -> None:
    config = context.op_execution_context.op_config
    argumentos = ["coletar", "--medicoes"]
    if "ano_inicio" in config:
        argumentos.extend(("--de-ano", str(config["ano_inicio"])))
    if "ano_fim" in config:
        argumentos.extend(("--ate-ano", str(config["ano_fim"])))
    for estacao in config["estacoes"]:
        argumentos.extend(("--estacao", estacao))
    executar(context, clima.main, *argumentos)


@asset(
    group_name="clima",
    deps=[clima_medicoes],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Promove as medições diárias do Delta para bronze.clima_medicao.",
)
def clima_medicoes_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_clima.main, "--tabela", "medicao")
