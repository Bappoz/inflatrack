"""Ativos do dbt: os modelos da Silver e da Gold e os testes do dbt dentro do grafo do Dagster.

Cada modelo, seed e teste de `dbt/` vira um ativo (ou um *asset check*) sem código novo: um
modelo que um colega cria aparece aqui sozinho. A ligação com a Bronze sai do próprio
`_<fonte>__sources.yml`: a tabela declara o ativo do loader que a escreve em
`config.meta.dagster.asset_key` (ver `dbt/README.md`), e o dbt passa a rodar depois dele.

O `dbt build` escreve em `silver` e `gold` no mesmo arquivo DuckDB dos loaders, então entra
no pool `duckdb_writer` como eles. Os modelos rodam sozinhos quando um ativo de cima é
atualizado (`AutomationCondition.eager`), desde que o sensor de automação esteja ligado na
interface; como os agendamentos, ele nasce desligado.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dagster import AssetExecutionContext, AutomationCondition
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets

from orchestration.assets.comum import POOL_DUCKDB

RAIZ = Path(__file__).resolve().parents[2]

PROJETO_DBT = DbtProject(project_dir=RAIZ, profiles_dir=RAIZ)
# Em `dagster dev` o manifesto é refeito a cada carga. Fora dele (testes, CI, clone limpo), o
# `target/` não é versionado: sem manifesto, o grafo não carrega, então ele é gerado aqui.
PROJETO_DBT.prepare_if_dev()
if not PROJETO_DBT.manifest_path.exists():
    PROJETO_DBT.preparer.prepare(PROJETO_DBT)

# Pasta de topo em dbt/models/ (ou seeds) -> grupo no Dagster: a camada do Medallion.
GRUPO_POR_PASTA = {
    "staging": "silver",
    "intermediate": "silver",
    "marts": "gold",
    "semantic": "gold",
}


class TradutorInflatrack(DagsterDbtTranslator):
    def get_group_name(self, dbt_resource_props: Mapping[str, Any]) -> str | None:
        if dbt_resource_props["resource_type"] == "seed":
            return "silver"
        caminho = dbt_resource_props.get("fqn", [])
        pasta = caminho[1] if len(caminho) > 1 else ""
        return GRUPO_POR_PASTA.get(pasta, super().get_group_name(dbt_resource_props))

    def get_automation_condition(
        self, dbt_resource_props: Mapping[str, Any]
    ) -> AutomationCondition | None:
        return AutomationCondition.eager()


@dbt_assets(
    manifest=PROJETO_DBT.manifest_path,
    project=PROJETO_DBT,
    dagster_dbt_translator=TradutorInflatrack(),
    pool=POOL_DUCKDB,
)
def dbt_inflatrack(context: AssetExecutionContext):
    """`dbt build` dos modelos selecionados: cria as views e tabelas e roda os testes."""
    yield from DbtCliResource(project_dir=PROJETO_DBT).cli(["build"], context=context).stream()
