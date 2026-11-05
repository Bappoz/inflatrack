"""Ativos da fonte `pib`: SIDRA 1846 → Bronze em Delta → `bronze.pib_valor` no DuckDB.

A coleta é particionada por ano (`partitions.PIB_ANUAL`): a coleta já faz uma requisição
por ano, então reprocessar anos passados (*backfill*) custa só as requisições desses anos.
Um backfill de vários anos roda numa execução só (`BackfillPolicy.single_run`), com
`--de`/`--ate`. O ano corrente sem trimestre publicado é pulado e a partição dele fica
pendente (`materializar_coletadas`). A carga no DuckDB não é particionada: ela espelha o
Delta inteiro e só acrescenta linhas novas, então rodar de novo não duplica nada.
"""

from collections.abc import Iterator
from pathlib import Path

from dagster import AssetExecutionContext, AssetMaterialization, BackfillPolicy, asset

from inflatrack import load_pib
from inflatrack.bronze import pib as bronze_pib
from orchestration.assets.comum import (
    POOL_DUCKDB,
    RETRY_REDE,
    executar,
    materializar_coletadas,
)
from orchestration.partitions import PIB_ANUAL


@asset(
    group_name="pib",
    partitions_def=PIB_ANUAL,
    backfill_policy=BackfillPolicy.single_run(),
    retry_policy=RETRY_REDE,
    kinds={"python", "delta"},
    description="Contas nacionais trimestrais (SIDRA 1846), uma partição por ano desde 1996.",
    output_required=False,
)
def pib_parquet(context: AssetExecutionContext) -> Iterator[AssetMaterialization]:
    faixa = context.partition_key_range
    context.log.info("pib: %s a %s", faixa.start, faixa.end)
    destino = Path(bronze_pib.DIRETORIO_PADRAO)
    gravacao = bronze_pib.coletar(destino, int(faixa.start), int(faixa.end))
    yield from materializar_coletadas(context, (str(ano) for ano in gravacao.anos))


@asset(
    group_name="pib",
    deps=[pib_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Espelha o Delta do PIB em bronze.pib_valor no DuckDB (só acrescenta).",
)
def pib_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_pib.main)
