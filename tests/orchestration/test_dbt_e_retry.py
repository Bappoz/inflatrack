"""Nível 4: dbt dentro do grafo do Dagster e retentativa quando a API cai (HTTP 503)."""

import httpx
import pytest
from dagster import AssetKey, RetryPolicy, asset, instance_for_test, materialize

from orchestration.assets import commodities, dolar, pib, selic
from orchestration.assets.comum import POOL_DUCKDB, RETRY_REDE, executar
from orchestration.definitions import defs

GRAFO = defs.get_repository_def().asset_graph


def _pais(*chave: str) -> set[str]:
    return {pai.to_user_string() for pai in GRAFO.get(AssetKey(list(chave))).parent_keys}


@pytest.mark.parametrize(
    ("modelo", "loader"),
    [
        ("stg_pib__valor", "pib_duckdb"),
        ("stg_commodities__cotacao", "commodities_duckdb"),
        ("stg_dolar__cotacao_diaria", "dolar_duckdb"),
        ("stg_selic__taxa_diaria", "selic_duckdb"),
    ],
)
def test_staging_do_dbt_roda_depois_do_loader_da_bronze(modelo: str, loader: str) -> None:
    """A ligação vem do meta.dagster.asset_key do _<fonte>__sources.yml."""
    assert loader in _pais("silver", modelo)


def test_intermediate_depende_da_staging_da_mesma_fonte() -> None:
    assert "silver/stg_pib__valor" in _pais("silver", "int_pib__mensal")
    assert "silver/stg_commodities__cotacao" in _pais("silver", "int_commodities__mensal")
    assert "silver/stg_dolar__cotacao_diaria" in _pais("silver", "int_macroeconomia__mensal")
    assert "silver/stg_selic__taxa_diaria" in _pais("silver", "int_macroeconomia__mensal")


def test_ativos_do_dbt_ficam_no_pool_e_no_grupo_da_camada() -> None:
    ativos_dbt = [chave for chave in GRAFO.get_all_asset_keys() if "dbt" in GRAFO.get(chave).kinds]
    assert ativos_dbt
    for chave in ativos_dbt:
        no = GRAFO.get(chave)
        assert no.pools == {POOL_DUCKDB}, chave.to_user_string()
        assert no.group_name == chave.path[0], chave.to_user_string()  # silver/... ou gold/...
        assert no.automation_condition is not None, chave.to_user_string()


def test_testes_do_dbt_viram_asset_checks() -> None:
    checados = {chave.asset_key.to_user_string() for chave in GRAFO.asset_check_keys}
    assert {
        "silver/int_pib__mensal",
        "silver/int_commodities__mensal",
        "silver/int_macroeconomia__mensal",
    } <= checados


def test_politica_de_retry_por_fonte() -> None:
    """PIB, Dólar e Selic tentam de novo se a rede cair; commodities não para poupar cota."""
    assert pib.pib_parquet.op.retry_policy == RETRY_REDE
    assert dolar.dolar_parquet.op.retry_policy == RETRY_REDE
    assert selic.selic_parquet.op.retry_policy == RETRY_REDE
    assert commodities.commodities_parquet.op.retry_policy is None


def test_dagster_tenta_de_novo_quando_a_api_devolve_503() -> None:
    """Mesma política do RETRY_REDE, sem a espera de 30 s, e o mesmo `executar` dos ativos."""
    chamadas = []

    def ingestor_que_cai_uma_vez(argv: list[str]) -> int:
        chamadas.append(argv)
        if len(chamadas) == 1:
            requisicao = httpx.Request("GET", "https://apisidra.ibge.gov.br/values/t/1846")
            raise httpx.HTTPStatusError(
                "503 Service Unavailable",
                request=requisicao,
                response=httpx.Response(503, request=requisicao),
            )
        return 0

    @asset(retry_policy=RetryPolicy(max_retries=RETRY_REDE.max_retries, delay=0))
    def ingestao_instavel(context) -> None:
        executar(context, ingestor_que_cai_uma_vez)

    with instance_for_test() as instancia:
        resultado = materialize([ingestao_instavel], instance=instancia, raise_on_error=False)
        eventos = resultado.all_events

    assert resultado.success
    assert len(chamadas) == 2
    tentativas = [evento for evento in eventos if evento.event_type_value == "STEP_UP_FOR_RETRY"]
    assert len(tentativas) == 1


def test_sem_retry_a_falha_da_api_derruba_o_ativo() -> None:
    def ingestor_fora_do_ar(argv: list[str]) -> int:
        requisicao = httpx.Request("GET", "https://www.alphavantage.co/query")
        raise httpx.HTTPStatusError(
            "503", request=requisicao, response=httpx.Response(503, request=requisicao)
        )

    @asset
    def ingestao_sem_retry(context) -> None:
        executar(context, ingestor_fora_do_ar)

    with instance_for_test() as instancia:
        resultado = materialize([ingestao_sem_retry], instance=instancia, raise_on_error=False)
    assert not resultado.success
