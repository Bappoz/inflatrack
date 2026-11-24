"""Ativo do site: publica no Supabase a previsão, os nomes, o resumo, os gráficos e o dashboard.

O site e o agente não acessam o ambiente local; leem só o que este ativo grava (ver
`inflatrack.reverse_etl.publicar_site` e `web/backend/migrations/003_publicacao_inflatrack.sql`).
Lê a Gold (só leitura), por isso entra no pool `duckdb_writer`. Sem dependentes: nada do
pipeline lê o Supabase de volta. Roda no `predicao_job` (previsão nova) e no fim do
`dashboard_job` (IPCA novo).
"""

import os

from dagster import AssetExecutionContext, AssetKey, Failure, asset
from dotenv import load_dotenv

from inflatrack.reverse_etl import publicar_site
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar


@asset(
    group_name="site",
    # Os gráficos e o dashboard por praça saem da `serie`: publica depois da cópia para lá.
    deps=[AssetKey(["gold", "fct_previsao_subitem"]), AssetKey("dashboard_serie_postgres")],
    pool=POOL_DUCKDB,
    retry_policy=RETRY_REDE,
    kinds={"python", "duckdb", "postgres"},
    description="Publicação no Supabase do que o site e o agente leem (sem preço, ADR 0004).",
)
def site_supabase(context: AssetExecutionContext) -> None:
    load_dotenv(".env")
    if not os.environ.get(publicar_site.VARIAVEL_DSN, "").strip():
        # Configuração faltando não se resolve esperando: sem retry.
        raise Failure(
            f"{publicar_site.VARIAVEL_DSN} vazio no .env: preencha com a URL de Postgres do"
            " projeto do Supabase (Project Settings > Database > Connection string)",
            allow_retries=False,
        )
    executar(context, publicar_site.main)
