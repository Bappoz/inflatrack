"""Ativos da fonte IPCA/INPC: SIDRA → Bronze em Delta + Postgres → `bronze.ipca_*` no DuckDB.

A coleta é particionada por mês (`partitions.py`): cada mês já é uma requisição, e a API recusa
dois meses de uma vez. Um backfill vira uma execução só (`BackfillPolicy.single_run`), e
`segmentos_ipca` esconde a troca de agregado do IBGE (2938 → 1419 → 7060). A carga no DuckDB
não é particionada: ela espelha o Delta inteiro e só acrescenta linhas novas.

Os ativos não reimplementam nada: chamam o mesmo `main(argv)` que o `justfile` chama e
transformam código de saída ≠ 0 em falha do Dagster.
"""

from dagster import (
    AssetExecutionContext,
    AssetSpec,
    BackfillPolicy,
    MaterializeResult,
    asset,
    multi_asset,
)

from inflatrack.bronze import ipca as bronze_ipca
from inflatrack.loaders import load_ipca
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar
from orchestration.partitions import (
    INPC_MENSAL,
    IPCA_INDICE_MENSAL,
    IPCA_MENSAL,
    formato_sidra,
    mes_da_chave,
    segmentos_ipca,
)


def _intervalo(context: AssetExecutionContext):
    faixa = context.partition_key_range
    return mes_da_chave(faixa.start), mes_da_chave(faixa.end)


def _coletar(context: AssetExecutionContext, agregado: int, de, ate) -> None:
    executar(
        context,
        bronze_ipca.main,
        "coletar",
        "--agregado", str(agregado),
        "--de", formato_sidra(de),
        "--ate", formato_sidra(ate),
    )  # fmt: skip


@asset(
    group_name="sidra",
    partitions_def=IPCA_MENSAL,
    backfill_policy=BackfillPolicy.single_run(),
    retry_policy=RETRY_REDE,
    kinds={"python", "delta", "postgres"},
    description="IPCA mensal por subitem e região (agregados 2938, 1419 e 7060).",
)
def ipca(context: AssetExecutionContext) -> None:
    inicio, fim = _intervalo(context)
    for agregado, de, ate in segmentos_ipca(inicio, fim):
        _coletar(context, agregado, de, ate)


@asset(
    group_name="sidra",
    partitions_def=INPC_MENSAL,
    backfill_policy=BackfillPolicy.single_run(),
    retry_policy=RETRY_REDE,
    kinds={"python", "delta", "postgres"},
    description="INPC mensal por subitem e região (agregado 7063).",
)
def inpc(context: AssetExecutionContext) -> None:
    _coletar(context, 7063, *_intervalo(context))


@asset(
    group_name="sidra",
    partitions_def=IPCA_INDICE_MENSAL,
    backfill_policy=BackfillPolicy.single_run(),
    retry_policy=RETRY_REDE,
    kinds={"python", "delta", "postgres"},
    description="Número-índice do IPCA, Brasil (agregado 1737).",
)
def ipca_numero_indice(context: AssetExecutionContext) -> None:
    _coletar(context, 1737, *_intervalo(context))


# Dois ativos, um passo só: o dbt exige uma chave de ativo por `source`, e o loader escreve as duas
# tabelas juntas. A observação sem os metadados da mesma carga não teria como ser traduzida.
@multi_asset(
    name="ipca_carga_duckdb",
    group_name="sidra",
    pool=POOL_DUCKDB,
    specs=[
        AssetSpec(
            "ipca_duckdb",
            deps=[ipca, inpc, ipca_numero_indice],
            kinds={"python", "duckdb"},
            description="Espelha o Delta do IPCA em bronze.ipca_observacao (só acrescenta).",
        ),
        AssetSpec(
            "ipca_metadados_duckdb",
            deps=[ipca, inpc, ipca_numero_indice],
            kinds={"python", "duckdb"},
            description="Espelha o Delta da cesta em bronze.ipca_metadados (só acrescenta).",
        ),
    ],
)
def ipca_carga_duckdb(context: AssetExecutionContext):
    executar(context, load_ipca.main)
    yield MaterializeResult(asset_key="ipca_duckdb")
    yield MaterializeResult(asset_key="ipca_metadados_duckdb")
