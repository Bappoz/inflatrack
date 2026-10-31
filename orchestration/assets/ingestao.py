"""Ativos das fontes que ainda não têm módulo próprio (ver `pib.py` e `commodities.py`).

Um ativo por etapa de ingestão/carga, envolvendo os módulos de `src/inflatrack/`.

Os ativos não reimplementam nada: chamam o mesmo `main(argv)` que o `justfile` chama
e transformam código de saída ≠ 0 em falha do Dagster. Idempotência continua sendo
responsabilidade do código de ingestão (Raw imutável e `ON CONFLICT DO UPDATE`).

Todo ativo que escreve no DuckDB entra no pool `duckdb_writer` (limite 1, ver
`.dagster/dagster.yaml`): o arquivo aceita um único escritor por vez.
"""

from dagster import AssetExecutionContext, asset

from inflatrack import (
    ingest_dolar,
    ingest_pib_china,
    ingest_selic,
    load_pib_china,
)
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar

# --- Dólar e Selic (BCB → DuckDB) ---------------------------------------------------


@asset(
    group_name="macro",
    pool=POOL_DUCKDB,
    retry_policy=RETRY_REDE,
    kinds={"python", "duckdb"},
    description="Dólar comercial PTAX diário (API Olinda), de 2020 até hoje.",
)
def dolar(context: AssetExecutionContext) -> None:
    executar(context, ingest_dolar.main, "--de", "2020-01-01")


@asset(
    group_name="macro",
    pool=POOL_DUCKDB,
    retry_policy=RETRY_REDE,
    kinds={"python", "duckdb"},
    description="Taxa Selic diária (SGS), de 2020 até hoje.",
)
def selic(context: AssetExecutionContext) -> None:
    executar(context, ingest_selic.main, "--de", "2020-01-01")


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
