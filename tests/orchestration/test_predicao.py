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
