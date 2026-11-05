"""Ativos da fonte IPCA/INPC: SIDRA → Bronze em Delta + Postgres → `bronze.ipca_*` no DuckDB.

A coleta é particionada por mês (`partitions.py`): cada mês já é uma requisição, e a API recusa
dois meses de uma vez. Um backfill vira uma execução só (`BackfillPolicy.single_run`), e
`segmentos_ipca` esconde a troca de agregado do IBGE (2938 → 1419 → 7060). A carga no DuckDB
não é particionada: ela espelha o Delta inteiro e só acrescenta linhas novas.

A coleta chama a mesma função que o `coletar` do `justfile` (`coletar_intervalo`), porque o
ativo precisa saber quais meses vieram: mês ainda não divulgado é pulado e a partição dele
fica pendente (`materializar_coletadas`). A carga no DuckDB chama o `main(argv)` do loader.
"""

from collections.abc import Iterator
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    AssetMaterialization,
    AssetSpec,
    BackfillPolicy,
    MaterializeResult,
    asset,
    multi_asset,
)

from inflatrack.bronze import ipca as bronze_ipca
from inflatrack.loaders import load_ipca
from orchestration.assets.comum import (
    POOL_DUCKDB,
    RETRY_REDE,
    executar,
    materializar_coletadas,
)
from orchestration.partitions import (
    INPC_MENSAL,
    IPCA_INDICE_MENSAL,
    IPCA_MENSAL,
    mes_da_chave,
    segmentos_ipca,
)


def _intervalo(context: AssetExecutionContext):
    faixa = context.partition_key_range
    return mes_da_chave(faixa.start), mes_da_chave(faixa.end)


def _coletar(context: AssetExecutionContext, agregado: int, de, ate) -> list[str]:
    """Coleta um trecho e devolve as chaves de partição ('2026-09-01') dos meses gravados."""
    context.log.info("agregado %d: %s a %s", agregado, f"{de:%Y-%m}", f"{ate:%Y-%m}")
    periodos = bronze_ipca.coletar_intervalo(agregado, de, ate, Path(bronze_ipca.DIRETORIO_PADRAO))
    return [f"{periodo[:4]}-{periodo[4:]}-01" for periodo in periodos]


@asset(
    group_name="sidra",
    partitions_def=IPCA_MENSAL,
    backfill_policy=BackfillPolicy.single_run(),
    retry_policy=RETRY_REDE,
    kinds={"python", "delta", "postgres"},
    description="IPCA mensal por subitem e região (agregados 2938, 1419 e 7060).",
    output_required=False,
)
def ipca(context: AssetExecutionContext) -> Iterator[AssetMaterialization]:
    inicio, fim = _intervalo(context)
    coletadas = []
    for agregado, de, ate in segmentos_ipca(inicio, fim):
        coletadas += _coletar(context, agregado, de, ate)
    yield from materializar_coletadas(context, coletadas)


@asset(
    group_name="sidra",
    partitions_def=INPC_MENSAL,
    backfill_policy=BackfillPolicy.single_run(),
    retry_policy=RETRY_REDE,
    kinds={"python", "delta", "postgres"},
    description="INPC mensal por subitem e região (agregado 7063).",
    output_required=False,
)
def inpc(context: AssetExecutionContext) -> Iterator[AssetMaterialization]:
    yield from materializar_coletadas(context, _coletar(context, 7063, *_intervalo(context)))


@asset(
    group_name="sidra",
    partitions_def=IPCA_INDICE_MENSAL,
    backfill_policy=BackfillPolicy.single_run(),
    retry_policy=RETRY_REDE,
    kinds={"python", "delta", "postgres"},
    description="Número-índice do IPCA, Brasil (agregado 1737).",
    output_required=False,
)
def ipca_numero_indice(context: AssetExecutionContext) -> Iterator[AssetMaterialization]:
    yield from materializar_coletadas(context, _coletar(context, 1737, *_intervalo(context)))


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
