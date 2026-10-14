"""Um ativo por etapa de ingestão/carga, envolvendo os módulos de `src/inflatrack/`.

Os ativos não reimplementam nada: chamam o mesmo `main(argv)` que o `justfile` chama
e transformam código de saída ≠ 0 em falha do Dagster. Idempotência continua sendo
responsabilidade do código de ingestão (Raw imutável e `ON CONFLICT DO UPDATE`).

Todo ativo que escreve no DuckDB entra no pool `duckdb_writer` (limite 1, ver
`.dagster/dagster.yaml`): o arquivo aceita um único escritor por vez.
"""

import time
from collections.abc import Callable

from dagster import (
    AssetExecutionContext,
    BackfillPolicy,
    Backoff,
    Failure,
    RetryPolicy,
    asset,
)

from inflatrack import (
    ingest,
    ingest_commodities,
    ingest_dolar,
    ingest_pib,
    ingest_pib_china,
    ingest_selic,
    load_commodities,
    load_pib,
    load_pib_china,
)
from inflatrack.alphavantage import AlphaVantageClient
from orchestration.partitions import (
    INPC_MENSAL,
    IPCA_INDICE_MENSAL,
    IPCA_MENSAL,
    formato_sidra,
    mes_da_chave,
    segmentos_ipca,
)

POOL_DUCKDB = "duckdb_writer"

# Falha de rede costuma ser passageira: 2 retries, esperando 30 s e 90 s
# (o backoff exponencial do Dagster é (2^n - 1) × delay).
RETRY_REDE = RetryPolicy(max_retries=2, delay=30, backoff=Backoff.EXPONENTIAL)


def _executar(context: AssetExecutionContext, main: Callable[..., int], *argv: str) -> None:
    context.log.info("%s %s", main.__module__, " ".join(argv))
    codigo = main(list(argv))
    if codigo != 0:
        raise Failure(f"{main.__module__} terminou com código {codigo}")


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
        _executar(
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
    _executar(
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
    _executar(
        context,
        ingest.main,
        "--agregado", "1737",
        "--de", formato_sidra(inicio),
        "--ate", formato_sidra(fim),
    )  # fmt: skip


# --- Dólar e Selic (BCB → DuckDB) ---------------------------------------------------


@asset(
    group_name="macro",
    pool=POOL_DUCKDB,
    retry_policy=RETRY_REDE,
    kinds={"python", "duckdb"},
    description="Dólar comercial PTAX diário (API Olinda), de 2020 até hoje.",
)
def dolar(context: AssetExecutionContext) -> None:
    _executar(context, ingest_dolar.main, "--de", "2020-01-01")


@asset(
    group_name="macro",
    pool=POOL_DUCKDB,
    retry_policy=RETRY_REDE,
    kinds={"python", "duckdb"},
    description="Taxa Selic diária (SGS), de 2020 até hoje.",
)
def selic(context: AssetExecutionContext) -> None:
    _executar(context, ingest_selic.main, "--de", "2020-01-01")


# --- Commodities (Alpha Vantage → Parquet → DuckDB) ---------------------------------


@asset(
    group_name="commodities",
    kinds={"python", "parquet"},
    description="Cotações históricas das 9 commodities. Sem retry: a cota é de 25 req./dia.",
)
def commodities_parquet(context: AssetExecutionContext) -> None:
    # `ingest_commodity` registra o erro e segue; o Parquet não atualizado é o sinal.
    inicio = time.time()
    cliente = AlphaVantageClient()
    falhas = []
    for simbolo in ingest_commodities.COMMODITY_CONFIGS:
        ingest_commodities.ingest_commodity(cliente, simbolo, "historico")
        saida = ingest_commodities.get_parquet_dir() / f"{simbolo.lower()}_historico.parquet"
        if not saida.is_file() or saida.stat().st_mtime < inicio:
            falhas.append(simbolo)
    if falhas:
        raise Failure(f"commodities sem Parquet novo: {', '.join(falhas)}")


@asset(
    group_name="commodities",
    deps=[commodities_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
    description="Upsert das cotações em commodity_cotacao.",
)
def commodities_duckdb(context: AssetExecutionContext) -> None:
    load_commodities.load_data()


# --- PIB (SIDRA 1846 → Parquet → DuckDB) --------------------------------------------


@asset(
    group_name="pib",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet"},
    description="Contas nacionais trimestrais (SIDRA 1846), 1996 até hoje.",
)
def pib_parquet(context: AssetExecutionContext) -> None:
    _executar(context, ingest_pib.main)


@asset(group_name="pib", deps=[pib_parquet], pool=POOL_DUCKDB, kinds={"python", "duckdb"})
def pib_duckdb(context: AssetExecutionContext) -> None:
    _executar(context, load_pib.main)


# --- PIB da China (Banco Mundial → Parquet → DuckDB) --------------------------------


@asset(
    group_name="pib_china",
    retry_policy=RETRY_REDE,
    kinds={"python", "parquet"},
    description="Crescimento e PIB em US$ da China (World Bank), anual.",
)
def pib_china_parquet(context: AssetExecutionContext) -> None:
    _executar(context, ingest_pib_china.main)


@asset(
    group_name="pib_china",
    deps=[pib_china_parquet],
    pool=POOL_DUCKDB,
    kinds={"python", "duckdb"},
)
def pib_china_duckdb(context: AssetExecutionContext) -> None:
    _executar(context, load_pib_china.main)
