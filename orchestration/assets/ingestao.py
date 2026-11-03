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
    ingest_selic,
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
