"""Ativos, job e agendamento do RONI (ENSO) no Dagster."""

from unittest.mock import patch

from dagster import AssetKey, build_asset_context

from orchestration.assets import enso
from orchestration.definitions import defs
from orchestration.popular import JOBS_DE_FONTE
from orchestration.schedules import SCHEDULES


def test_enso_job_coleta_e_carrega_e_roda_toda_segunda():
    job = defs.resolve_job_def("enso_job")
    assert {k.to_user_string() for k in job.asset_layer.executable_asset_keys} == {
        "enso_parquet",
        "enso_duckdb",
    }
    (agendamento,) = [s for s in SCHEDULES if s.job_name == "enso_job"]
    assert agendamento.cron_schedule == "0 9 * * 1"
    assert "enso_job" in JOBS_DE_FONTE  # entra na primeira carga (popular_banco_job)


def test_gold_do_enso_depende_da_carga():
    grafo = defs.resolve_asset_graph()
    stg = AssetKey(["silver", "stg_enso__roni"])
    assert AssetKey("enso_duckdb") in grafo.get(stg).parent_keys
    assert stg in grafo.get(AssetKey(["gold", "fct_enso_mensal"])).parent_keys


def test_ativos_chamam_coleta_e_carga():
    with (
        patch.object(enso.enso, "main", return_value=0) as coletar,
        patch.object(enso.load_enso, "main", return_value=0) as carregar,
        build_asset_context() as context,
    ):
        enso.enso_parquet(context)
        enso.enso_duckdb(context)
    coletar.assert_called_once_with(["coletar"])
    carregar.assert_called_once_with([])
