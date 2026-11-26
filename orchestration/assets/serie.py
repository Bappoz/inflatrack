"""Ativos da vitrine: copiam tabelas da Gold para o schema `serie` do Postgres.

Roda depois que o dbt atualiza as tabelas da Gold listadas em
`inflatrack.reverse_etl.exportar_serie.TABELAS`. O Metabase lê só o Postgres, então é este
ativo que leva o resultado do pipeline até o painel. Abre o arquivo do DuckDB (só leitura),
por isso entra no pool `duckdb_writer`, como todo ativo que usa o arquivo.
"""

from dagster import AssetExecutionContext, AssetKey, AutomationCondition, asset

from inflatrack.common.db import dsn_do_ambiente
from inflatrack.reverse_etl import exportar_serie
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar


@asset(
    group_name="vitrine",
    deps=[AssetKey(["gold", tabela]) for tabela in exportar_serie.TABELAS],
    pool=POOL_DUCKDB,
    retry_policy=RETRY_REDE,
    kinds={"python", "duckdb", "postgres"},
    automation_condition=AutomationCondition.eager(),
    description="Cópia das tabelas da Gold para serie.* no Postgres, que o Metabase lê.",
)
def serie_postgres(context: AssetExecutionContext) -> None:
    executar(context, exportar_serie.main)


TABELAS_DASHBOARD = (
    "dim_calendario",
    "dim_localidade",
    "dim_cesta_ipca_scd2",
    "fct_inflacao_mensal",
)


@asset(
    name="dashboard_serie_postgres",
    group_name="vitrine",
    deps=[AssetKey(["gold", tabela]) for tabela in TABELAS_DASHBOARD],
    pool=POOL_DUCKDB,
    retry_policy=RETRY_REDE,
    kinds={"python", "duckdb", "postgres"},
    description=(
        "Publica no Postgres apenas as tabelas Gold usadas pelo dashboard público de inflação."
    ),
)
def dashboard_serie_postgres(context: AssetExecutionContext) -> None:
    conexao = exportar_serie.conectar(exportar_serie.DB_PADRAO, dsn_do_ambiente())
    try:
        copiadas = exportar_serie.exportar(conexao, tabelas=TABELAS_DASHBOARD)
    finally:
        conexao.close()
    context.log.info("tabelas do dashboard publicadas em serie: %s", copiadas)
