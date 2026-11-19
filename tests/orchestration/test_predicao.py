"""Previsão mensal e publicação no site: fora do analitico_job diário, num job próprio."""

from dagster import AssetKey

from orchestration.definitions import defs

PREVISAO = AssetKey(["gold", "fct_previsao_subitem"])


def _chave_previsao() -> AssetKey:
    grafo = defs.resolve_asset_graph()
    chaves = [c for c in grafo.get_all_asset_keys() if c.path[-1] == "fct_previsao_subitem"]
    assert len(chaves) == 1, chaves
    return chaves[0]


def test_previsao_fica_no_grupo_predicao_sem_automacao() -> None:
    no = defs.resolve_asset_graph().get(_chave_previsao())

    assert no.group_name == "predicao"
    assert no.automation_condition is None


def test_analitico_job_nao_roda_a_previsao() -> None:
    job = defs.resolve_job_def("analitico_job")

    assert _chave_previsao() not in job.asset_layer.executable_asset_keys


SITE = AssetKey("site_supabase")


def test_predicao_job_preve_e_publica_e_e_mensal() -> None:
    from orchestration.schedules import SCHEDULES

    job = defs.resolve_job_def("predicao_job")
    agendas = {a.job_name: a.cron_schedule for a in SCHEDULES}

    assert job.asset_layer.executable_asset_keys == {PREVISAO, SITE}
    assert agendas["predicao_job"] == "0 11 14 * *"


def test_publicacao_depende_da_previsao_usa_o_pool_e_nao_tem_dependentes() -> None:
    from orchestration.assets.comum import POOL_DUCKDB

    no = defs.resolve_asset_graph().get(SITE)

    assert no.parent_keys == {PREVISAO}
    assert no.child_keys == set()
    assert no.pools == {POOL_DUCKDB}


def test_sem_url_do_supabase_falha_sem_retry(monkeypatch) -> None:
    import pytest
    from dagster import Failure, build_asset_context

    from orchestration.assets import site

    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.setattr(site, "load_dotenv", lambda *a, **k: None)

    with pytest.raises(Failure) as erro:
        site.site_supabase(build_asset_context())

    assert erro.value.allow_retries is False
    assert "SUPABASE_DB_URL" in str(erro.value)
