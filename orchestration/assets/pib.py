"""Ativos da fonte `pib`: SIDRA 1846 → Bronze em Delta → `bronze.pib_valor` no DuckDB.

A coleta é particionada por ano (`partitions.PIB_ANUAL`): o ingestor já faz uma requisição
por ano, então reprocessar anos passados (*backfill*) custa só as requisições desses anos.
Um backfill de vários anos roda numa execução só (`BackfillPolicy.single_run`), com
`--de`/`--ate`. A carga no DuckDB não é particionada: ela espelha o Delta inteiro e só
acrescenta linhas novas, então rodar de novo não duplica nada.
"""

from dagster import AssetExecutionContext, BackfillPolicy, asset

from inflatrack import ingest_pib, load_pib
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar
from orchestration.partitions import PIB_ANUAL


@asset(
    group_name="pib",
    partitions_def=PIB_ANUAL,
    backfill_policy=BackfillPolicy.single_run(),
    retry_policy=RETRY_REDE,
    kinds={"python", "delta"},
    description="Contas nacionais trimestrais (SIDRA 1846), uma partição por ano desde 1996.",
)
def pib_parquet(context: AssetExecutionContext) -> None:
    faixa = context.partition_key_range
    executar(context, ingest_pib.main, "--de", faixa.start, "--ate", faixa.end)


@asset(
    group_name="pib",
    deps=[pib_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Espelha o Delta do PIB em bronze.pib_valor no DuckDB (só acrescenta).",
)
def pib_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_pib.main)
