"""Testes dos Asset Checks de SLA, Freshness e volume no Dagster."""

from dagster import AssetCheckSeverity, build_asset_check_context

from orchestration.assets.checks import (
    check_dolar_freshness_e_volume,
    check_macroeconomia_mensal_freshness,
    check_selic_freshness_e_volume,
)
from orchestration.definitions import defs


def test_asset_checks_registrados_nas_definicoes():
    """Valida se os checks de SLA e Freshness foram carregados no grafo do Dagster."""
    repo = defs.get_repository_def()
    check_keys = {
        (ck.asset_key.to_user_string(), ck.name) for ck in repo.asset_graph.asset_check_keys
    }

    assert ("dolar_duckdb", "check_dolar_freshness_e_volume") in check_keys
    assert ("selic_duckdb", "check_selic_freshness_e_volume") in check_keys
    assert (
        "silver/int_macroeconomia__mensal",
        "check_macroeconomia_mensal_freshness",
    ) in check_keys


def test_check_dolar_executa_e_valida_sla():
    """Valida a execução do check de freshness e volume do Dólar."""
    context = build_asset_check_context()
    res = check_dolar_freshness_e_volume(context)

    assert "sla_declarado" in res.metadata
    assert res.metadata["total_linhas"].value >= 100
    assert "data_mais_recente" in res.metadata


def test_check_selic_executa_e_valida_sla():
    """Valida a execução do check de freshness e volume da Selic."""
    context = build_asset_check_context()
    res = check_selic_freshness_e_volume(context)

    assert "sla_declarado" in res.metadata
    assert res.metadata["total_linhas"].value >= 100
    assert "data_mais_recente" in res.metadata


def test_check_macroeconomia_mensal_executa_e_valida_sla():
    """Valida a execução do check de freshness na tabela de consumo intermediária."""
    context = build_asset_check_context()
    res = check_macroeconomia_mensal_freshness(context)

    assert "sla_declarado" in res.metadata
    assert res.metadata["total_meses"].value >= 12
    assert "mes_mais_recente" in res.metadata


def test_check_falha_quando_duckdb_nao_existe(tmp_path, monkeypatch):
    """Valida comportamento defensivo caso o banco não exista."""
    monkeypatch.setattr("orchestration.assets.checks.DB_PADRAO", tmp_path / "inexistente.duckdb")
    context = build_asset_check_context()

    res = check_dolar_freshness_e_volume(context)
    assert not res.passed
    assert res.severity == AssetCheckSeverity.ERROR
