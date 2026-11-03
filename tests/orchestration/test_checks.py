"""Testes dos Asset Checks de SLA, Freshness e volume no Dagster.

Rodam contra um DuckDB temporário (não dependem do `data/` da máquina).
"""

from datetime import date, timedelta

import duckdb
import pytest
from dagster import AssetCheckSeverity, build_asset_check_context

from orchestration.assets import checks
from orchestration.assets.checks import (
    check_dolar_freshness_e_volume,
    check_macroeconomia_mensal_freshness,
    check_selic_freshness_e_volume,
)
from orchestration.assets.comum import POOL_DUCKDB
from orchestration.definitions import defs


def _banco(caminho, ultimo_dia: date, dias: int = 150, meses: int = 24) -> None:
    with duckdb.connect(str(caminho)) as con:
        con.execute("create schema bronze; create schema gold")
        for tabela in ("dolar_boletim", "selic_taxa"):
            con.execute(
                f"create table bronze.{tabela} as select (?::date - i::int) as data_referencia "
                "from range(?) t(i)",
                [ultimo_dia, dias],
            )
        con.execute(
            "create table gold.fct_macroeconomia_mensal as "
            "select (date_trunc('month', ?::date) - to_months(i::int))::date as mes_referencia "
            "from range(?) t(i)",
            [ultimo_dia, meses],
        )


@pytest.fixture
def banco_em_dia(tmp_path, monkeypatch):
    caminho = tmp_path / "inflatrack.duckdb"
    _banco(caminho, date.today() - timedelta(days=1))
    monkeypatch.setattr(checks, "DB_PADRAO", caminho)
    return caminho


def test_asset_checks_registrados_nas_definicoes():
    """Valida se os checks de SLA e Freshness foram carregados no grafo do Dagster."""
    repo = defs.get_repository_def()
    check_keys = {
        (ck.asset_key.to_user_string(), ck.name) for ck in repo.asset_graph.asset_check_keys
    }

    assert ("dolar_duckdb", "check_dolar_freshness_e_volume") in check_keys
    assert ("selic_duckdb", "check_selic_freshness_e_volume") in check_keys
    assert (
        "gold/fct_macroeconomia_mensal",
        "check_macroeconomia_mensal_freshness",
    ) in check_keys


def test_checks_que_abrem_o_duckdb_ficam_no_pool():
    """Uma conexão aberta no DuckDB, mesmo só leitura, trava o escritor (PLAN, Seção 6.3)."""
    for check in (
        check_dolar_freshness_e_volume,
        check_selic_freshness_e_volume,
        check_macroeconomia_mensal_freshness,
    ):
        assert check.node_def.pool == POOL_DUCKDB


def test_check_dolar_executa_e_valida_sla(banco_em_dia):
    res = check_dolar_freshness_e_volume(build_asset_check_context())

    assert res.passed
    assert "sla_declarado" in res.metadata
    assert res.metadata["total_linhas"].value >= 100


def test_check_selic_executa_e_valida_sla(banco_em_dia):
    res = check_selic_freshness_e_volume(build_asset_check_context())

    assert res.passed
    assert res.metadata["total_linhas"].value >= 100


def test_check_macroeconomia_mensal_executa_e_valida_sla(banco_em_dia):
    """O SLA declarado é da tabela de consumo (Gold), não da Silver."""
    res = check_macroeconomia_mensal_freshness(build_asset_check_context())

    assert res.passed
    assert res.metadata["total_meses"].value >= 12
    assert "mes_mais_recente" in res.metadata


def test_sla_vencido_vira_alerta_e_volume_baixo_vira_erro(tmp_path, monkeypatch):
    caminho = tmp_path / "atrasado.duckdb"
    _banco(caminho, date.today() - timedelta(days=30), dias=10)
    monkeypatch.setattr(checks, "DB_PADRAO", caminho)

    res = check_dolar_freshness_e_volume(build_asset_check_context())

    assert not res.passed
    assert res.severity == AssetCheckSeverity.ERROR  # volume baixo pesa mais que o atraso


def test_check_falha_quando_duckdb_nao_existe(tmp_path, monkeypatch):
    """Valida comportamento defensivo caso o banco não exista."""
    monkeypatch.setattr(checks, "DB_PADRAO", tmp_path / "inexistente.duckdb")
    context = build_asset_check_context()

    res = check_dolar_freshness_e_volume(context)
    assert not res.passed
    assert res.severity == AssetCheckSeverity.ERROR


def test_analitico_job_roda_silver_gold_e_vitrine_depois_das_fontes():
    """Rotina diária: depois do último agendamento de fonte (Dólar/Selic às 19h)."""
    repo = defs.get_repository_def()
    job = repo.get_job("analitico_job")
    chaves = {chave.to_user_string() for chave in job.asset_layer.selected_asset_keys}
    agendamento = next(s for s in repo.schedule_defs if s.job_name == "analitico_job")

    assert {"gold/fct_macroeconomia_mensal", "silver/int_macroeconomia__mensal"} <= chaves
    assert "serie_postgres" in chaves
    # As fontes têm job próprio, menos a carga do IPCA: ela não é particionada e depende dos três
    # ativos mensais, então vem aqui, antes do dbt.
    cargas = {chave for chave in chaves if chave.endswith("_duckdb")}
    assert cargas == {"ipca_duckdb", "ipca_metadados_duckdb"}
    assert agendamento.cron_schedule == "30 20 * * *"
