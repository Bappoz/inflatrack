"""Ativos das fontes que ainda não têm módulo próprio (ver `pib.py` e `commodities.py`).

Um ativo por etapa de ingestão/carga, envolvendo os módulos de `src/inflatrack/`.

Os ativos não reimplementam nada: chamam o mesmo `main(argv)` que o `justfile` chama
e transformam código de saída ≠ 0 em falha do Dagster. Idempotência continua sendo
responsabilidade do código de ingestão (Raw imutável e `ON CONFLICT DO UPDATE`).

Todo ativo que escreve no DuckDB entra no pool `duckdb_writer` (limite 1, ver
`.dagster/dagster.yaml`): o arquivo aceita um único escritor por vez.
"""

from dagster import AssetExecutionContext, BackfillPolicy, asset

from inflatrack import (
    ingest,
    ingest_pib_china,
    load_pib_china,
)
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar
from orchestration.partitions import (
    INPC_MENSAL,
    IPCA_INDICE_MENSAL,
    IPCA_MENSAL,
    formato_sidra,
    mes_da_chave,
    segmentos_ipca,
)

# --- IPCA/INPC (SIDRA → Postgres) -------------------------------------------------


def _intervalo(context: AssetExecutionContext):
    faixa = context.partition_key_range
    return mes_da_chave(faixa.start), mes_da_chave(faixa.end)


@asset(
    group_name="sidra",
    partitions_def=IPCA_MENSAL,
    backfill_policy=BackfillPolicy.single_run(),
    retry_policy=RETRY_REDE,
    kinds={"python", "postgres"},
    description="IPCA mensal por subitem e região (agregados 2938, 1419 e 7060).",
)
def ipca(context: AssetExecutionContext) -> None:
    inicio, fim = _intervalo(context)
    for agregado, de, ate in segmentos_ipca(inicio, fim):
        executar(
            context,
            ingest.main,
            "--agregado", str(agregado),
            "--de", formato_sidra(de),
            "--ate", formato_sidra(ate),
        )  # fmt: skip


@asset(
    group_name="sidra",
    partitions_def=INPC_MENSAL,
    backfill_policy=BackfillPolicy.single_run(),
    retry_policy=RETRY_REDE,
    kinds={"python", "postgres"},
    description="INPC mensal por subitem e região (agregado 7063).",
)
def inpc(context: AssetExecutionContext) -> None:
    inicio, fim = _intervalo(context)
    executar(
        context,
        ingest.main,
        "--agregado", "7063",
        "--de", formato_sidra(inicio),
        "--ate", formato_sidra(fim),
    )  # fmt: skip


@asset(
    group_name="sidra",
    partitions_def=IPCA_INDICE_MENSAL,
    backfill_policy=BackfillPolicy.single_run(),
    retry_policy=RETRY_REDE,
    kinds={"python", "postgres"},
    description="Número-índice do IPCA, Brasil (agregado 1737).",
)
def ipca_numero_indice(context: AssetExecutionContext) -> None:
    inicio, fim = _intervalo(context)
    executar(
        context,
        ingest.main,
        "--agregado", "1737",
        "--de", formato_sidra(inicio),
        "--ate", formato_sidra(fim),
    )  # fmt: skip


# --- PIB da China (Banco Mundial → Parquet → DuckDB) --------------------------------


@asset(
    group_name="pib_china",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet"},
    description="Crescimento e PIB em US$ da China (World Bank), anual.",
)
def pib_china_parquet(context: AssetExecutionContext) -> None:
    executar(context, ingest_pib_china.main)


@asset(
    group_name="pib_china",
    deps=[pib_china_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
)
def pib_china_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_pib_china.main)
