from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from dagster import AssetKey, build_asset_context, build_schedule_context, validate_run_config

from orchestration.assets import clima, dbt_assets
from orchestration.definitions import defs
from orchestration.schedules import agendamento_clima


def test_job_clima_inclui_coleta_e_carga_das_medicoes_sem_config():
    job = defs.resolve_job_def("clima_job")
    assert {chave.to_user_string() for chave in job.asset_layer.executable_asset_keys} == {
        "clima_parquet",
        "clima_duckdb",
        "clima_medicoes",
        "clima_medicoes_duckdb",
    }
    validate_run_config(job, {})
    grafo = defs.resolve_asset_graph()
    assert grafo.get(AssetKey("clima_medicoes_duckdb")).parent_keys == {
        AssetKey("clima_medicoes"),
        AssetKey("clima_duckdb"),
    }


def test_schedule_clima_fixa_sete_dias_completos_na_virada_do_ano():
    context = build_schedule_context(
        scheduled_execution_time=datetime(2027, 1, 3, 7, tzinfo=ZoneInfo("America/Sao_Paulo"))
    )
    (pedido,) = agendamento_clima.evaluate_tick(context).run_requests
    assert pedido.run_key == "clima-2027-01-02"
    assert pedido.run_config["ops"]["clima_medicoes"]["config"] == {
        "data_inicio": "2026-12-27",
        "data_fim": "2027-01-02",
    }
    validate_run_config(defs.resolve_job_def("clima_job"), pedido.run_config)


def test_asset_medicoes_usa_defaults_e_preserva_overrides():
    with patch.object(clima.ingest_clima, "main", return_value=0) as main:
        with build_asset_context() as context:
            clima.clima_medicoes(context)
        main.assert_called_once_with(["--medicoes"])
        main.reset_mock()
        with build_asset_context(
            asset_config={
                "estacoes": ["A001", "A002"],
                "data_inicio": "2026-01-01",
                "data_fim": "2026-01-31",
            }
        ) as context:
            clima.clima_medicoes(context)
        main.assert_called_once_with(
            [
                "--medicoes",
                "--de",
                "2026-01-01",
                "--ate",
                "2026-01-31",
                "--estacao",
                "A001",
                "--estacao",
                "A002",
            ]
        )


def test_dagster_prepara_banco_antes_de_executar_dbt():
    chamadas = []
    with (
        patch.object(dbt_assets, "init_db", side_effect=lambda: chamadas.append("init")),
        patch.object(dbt_assets, "DbtCliResource") as recurso,
    ):
        recurso.return_value.cli.side_effect = lambda *a, **k: (
            chamadas.append("dbt") or (recurso.return_value)
        )
        recurso.return_value.stream.return_value = iter(())
        with build_asset_context() as context:
            list(dbt_assets.dbt_inflatrack(context))
    assert chamadas == ["init", "dbt"]
