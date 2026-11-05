"""O que todo módulo de fonte usa: o pool do DuckDB, o retry de rede e a chamada do `main`.

Todo ativo que escreve no DuckDB entra no pool `duckdb_writer` (limite 1, ver
`.dagster/dagster.yaml`): o arquivo aceita um único escritor por vez.
"""

from collections.abc import Callable, Iterable, Iterator

from dagster import AssetExecutionContext, AssetMaterialization, Backoff, Failure, RetryPolicy

POOL_DUCKDB = "duckdb_writer"

# Falha de rede costuma ser passageira: 2 retries, esperando 30 s e 90 s
# (o backoff exponencial do Dagster é (2^n - 1) × delay).
RETRY_REDE = RetryPolicy(max_retries=2, delay=30, backoff=Backoff.EXPONENTIAL)


def executar(context: AssetExecutionContext, main: Callable[..., int], *argv: str) -> None:
    context.log.info("%s %s", main.__module__, " ".join(argv))
    codigo = main(list(argv))
    if codigo != 0:
        raise Failure(f"{main.__module__} terminou com código {codigo}")


def materializar_coletadas(
    context: AssetExecutionContext, coletadas: Iterable[str]
) -> Iterator[AssetMaterialization]:
    """Materializa só as partições que a fonte já publicou (ativo com `output_required=False`).

    Um backfill que termina num período ainda não divulgado (o mês corrente do IPCA, o ano
    corrente do PIB antes do 1º trimestre) traz o resto e deixa esse período como *faltando*,
    não como materializado: o agendamento continua pedindo até ele sair. Nenhuma partição
    publicada é falha, mas sem retry: esperar 30 s ou 90 s não faz a fonte publicar.
    """
    pedidas = context.partition_keys
    coletadas = set(coletadas)
    if not coletadas:
        raise Failure(
            f"nada de {pedidas[0]} a {pedidas[-1]} foi divulgado pela fonte ainda",
            allow_retries=False,
        )
    puladas = [chave for chave in pedidas if chave not in coletadas]
    if puladas:
        context.log.warning("ainda não divulgadas, ficam pendentes: %s", ", ".join(puladas))
    for chave in pedidas:
        if chave in coletadas:
            yield AssetMaterialization(asset_key=context.asset_key, partition=chave)
