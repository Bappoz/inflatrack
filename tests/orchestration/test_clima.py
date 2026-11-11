"""Grafo, configuração e agendamento dos ativos de clima no Dagster."""

from unittest.mock import patch

from dagster import AssetKey, build_asset_context, validate_run_config

from orchestration.assets import clima
from orchestration.definitions import defs
from orchestration.schedules import SCHEDULES


def test_job_clima_coleta_e_carrega_catalogo_e_medicoes_sem_config():
    job = defs.resolve_job_def("clima_job")
    assert {chave.to_user_string() for chave in job.asset_layer.executable_asset_keys} == {
        "clima_parquet",
        "clima_duckdb",
        "clima_medicoes",
        "clima_medicoes_duckdb",
    }
    validate_run_config(job, {})
    grafo = defs.resolve_asset_graph()
    assert grafo.get(AssetKey("clima_medicoes_duckdb")).parent_keys == {AssetKey("clima_medicoes")}


def test_clima_job_e_diario_sem_config_fixa():
    """O coletor decide o que baixar (HEAD + manifesto): o tick não precisa mandar datas."""
    (agendamento,) = [s for s in SCHEDULES if s.job_name == "clima_job"]
    assert agendamento.cron_schedule == "0 7 * * *"
    assert agendamento.execution_timezone == "America/Sao_Paulo"


def test_medicoes_usam_padroes_e_aceitam_carga_historica():
    with patch.object(clima.clima, "main", return_value=0) as main:
        with build_asset_context() as context:
            clima.clima_medicoes(context)
        main.assert_called_once_with(["coletar", "--medicoes"])
        main.reset_mock()
        with build_asset_context(
            asset_config={"estacoes": ["A001", "A002"], "ano_inicio": 2010, "ano_fim": 2012}
        ) as context:
            clima.clima_medicoes(context)
        main.assert_called_once_with(
            [
                "coletar",
                "--medicoes",
                "--de-ano",
                "2010",
                "--ate-ano",
                "2012",
                "--estacao",
                "A001",
                "--estacao",
                "A002",
            ]
        )


def test_cada_carga_do_duckdb_le_so_a_sua_tabela():
    with (
        patch.object(clima.load_clima, "main", return_value=0) as main,
        build_asset_context() as context,
    ):
        clima.clima_duckdb(context)
        clima.clima_medicoes_duckdb(context)
    assert [chamada.args[0] for chamada in main.call_args_list] == [
        ["--tabela", "estacao"],
        ["--tabela", "medicao"],
    ]


def test_gold_do_clima_depende_das_medicoes():
    grafo = defs.resolve_asset_graph()
    ancestrais, fila = set(), [AssetKey(["gold", "fct_clima_mensal"])]
    while fila:
        for pai in grafo.get(fila.pop()).parent_keys - ancestrais:
            ancestrais.add(pai)
            fila.append(pai)
    assert AssetKey("clima_medicoes_duckdb") in ancestrais
