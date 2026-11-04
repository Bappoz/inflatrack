"""O que todo módulo de fonte usa: o pool do DuckDB, o retry de rede e a chamada do `main`.

Todo ativo que escreve no DuckDB entra no pool `duckdb_writer` (limite 1, ver
`.dagster/dagster.yaml`): o arquivo aceita um único escritor por vez.
"""

from collections.abc import Callable

from dagster import AssetExecutionContext, Backoff, Failure, RetryPolicy

from inflatrack.common.bronze import SAIDA_NAO_DIVULGADO

POOL_DUCKDB = "duckdb_writer"

# Falha de rede costuma ser passageira: 2 retries, esperando 30 s e 90 s
# (o backoff exponencial do Dagster é (2^n - 1) × delay).
RETRY_REDE = RetryPolicy(max_retries=2, delay=30, backoff=Backoff.EXPONENTIAL)


def executar(context: AssetExecutionContext, main: Callable[..., int], *argv: str) -> None:
    context.log.info("%s %s", main.__module__, " ".join(argv))
    codigo = main(list(argv))
    if codigo == SAIDA_NAO_DIVULGADO:
        # Esperar 30 s ou 90 s não faz a fonte publicar: falha na hora, sem retry. O
        # agendamento pede de novo no dia seguinte.
        raise Failure(
            f"{main.__module__}: dado ainda não divulgado pela fonte; tente um intervalo"
            " que termine no último período publicado",
            allow_retries=False,
        )
    if codigo != 0:
        raise Failure(f"{main.__module__} terminou com código {codigo}")
