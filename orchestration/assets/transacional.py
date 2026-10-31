"""Ativos do banco do lojista: CDC do Postgres → Bronze em Delta → `bronze.transacional_mudanca`.

O CDC lê o slot lógico e só o avança depois de gravar no Delta: com o Postgres fora do ar, o
ativo falha, o retry tenta de novo e nenhum evento se perde, porque o WAL guarda o que o slot
ainda não consumiu. A carga no DuckDB espelha o Delta e só acrescenta linhas novas.
"""

from dagster import AssetExecutionContext, asset

from inflatrack.cdc import transacional
from inflatrack.loaders import load_transacional
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar


@asset(
    group_name="transacional",
    retry_policy=RETRY_REDE,
    kinds={"python", "postgres", "delta"},
    description="Mudanças de public (produto, preço, custo e venda) capturadas por CDC, sem CNPJ.",
)
def transacional_delta(context: AssetExecutionContext) -> None:
    executar(context, transacional.main)


@asset(
    group_name="transacional",
    deps=[transacional_delta],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Espelha o Delta do CDC em bronze.transacional_mudanca no DuckDB.",
)
def transacional_duckdb(context: AssetExecutionContext) -> None:
    executar(context, load_transacional.main)
