"""Testes dos Asset Checks de SLA, Freshness e volume no Dagster.

Rodam contra um DuckDB temporário (não dependem do `data/` da máquina).
"""

from datetime import date, timedelta

import duckdb
import pytest
from dagster import AssetCheckSeverity, build_asset_check_context

from orchestration.assets import checks
from orchestration.assets.checks import (
    check_clima_estacoes_freshness_e_volume,
    check_commodities_freshness_e_volume,
    check_dolar_freshness_e_volume,
    check_ipca_freshness_e_volume,
    check_macroeconomia_mensal_freshness,
    check_pib_freshness_e_volume,
    check_pib_internacional_freshness_e_volume,
    check_salario_minimo_freshness_e_volume,
    check_selic_freshness_e_volume,
)
from orchestration.assets.comum import POOL_DUCKDB
from orchestration.definitions import defs

TODOS_OS_CHECKS = (
    check_dolar_freshness_e_volume,
    check_selic_freshness_e_volume,
    check_macroeconomia_mensal_freshness,
    check_ipca_freshness_e_volume,
    check_salario_minimo_freshness_e_volume,
    check_pib_freshness_e_volume,
    check_pib_internacional_freshness_e_volume,
    check_clima_estacoes_freshness_e_volume,
    check_commodities_freshness_e_volume,
)


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
        _demais_fontes(con, ultimo_dia)


def _demais_fontes(con, ultimo_dia: date) -> None:
    """Uma tabela por fonte, com a coluna de data que o SLA dela lê e volume acima do mínimo."""
    mes = "date_trunc('month', ?::date) - to_months((i % 24)::int)"
    con.execute(
        f"create table bronze.ipca_observacao as select ({mes})::date as mes_referencia "
        "from range(1000000) t(i)",
        [ultimo_dia],
    )
    con.execute(
        f"create table bronze.salario_minimo_mes as select ({mes})::date as data_referencia "
        "from range(400) t(i)",
        [ultimo_dia],
    )
    con.execute(
        "create table bronze.pib_valor as select "
        "(date_trunc('quarter', ?::date) - to_months(((i % 40) * 3)::int))::date "
        "as data_referencia from range(1000) t(i)",
        [ultimo_dia],
    )
    con.execute(
        "create table bronze.pib_internacional_indicador as "
        "select (year(?::date) - (i % 5))::smallint as ano from range(300) t(i)",
        [ultimo_dia],
    )
    con.execute(
        "create table bronze.clima_estacao as select ?::timestamp as _ingerido_em "
        "from range(700) t(i)",
        [ultimo_dia],
    )
    con.execute(
        "create table bronze.commodities_cotacao as "
        "select 'WTI' as symbol, 'daily' as intervalo, (?::date - i::int) as data_referencia "
        "from range(150) t(i) "
        "union all "
        f"select 'COPPER', 'monthly', ({mes})::date from range(24) t(i)",
        [ultimo_dia, ultimo_dia],
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
    assert ("ipca_duckdb", "check_ipca_freshness_e_volume") in check_keys
    assert ("pib_duckdb", "check_pib_freshness_e_volume") in check_keys
    assert ("salario_minimo_duckdb", "check_salario_minimo_freshness_e_volume") in check_keys
    assert ("clima_duckdb", "check_clima_estacoes_freshness_e_volume") in check_keys
    assert ("commodities_duckdb", "check_commodities_freshness_e_volume") in check_keys
    assert (
        "pib_internacional_duckdb",
        "check_pib_internacional_freshness_e_volume",
    ) in check_keys


def test_checks_que_abrem_o_duckdb_ficam_no_pool():
    """Uma conexão aberta no DuckDB, mesmo só leitura, trava o escritor (PLAN, Seção 6.3)."""
    for check in TODOS_OS_CHECKS:
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
    assert res.metadata["total_linhas"].value >= 12
    assert "data_mais_recente" in res.metadata


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
    # As fontes têm job próprio, menos as cargas do IPCA e do PIB: não são particionadas e
    # dependem de coletas particionadas de saída opcional, então vêm aqui, antes do dbt.
    cargas = {chave for chave in chaves if chave.endswith("_duckdb")}
    assert cargas == {"ipca_duckdb", "ipca_metadados_duckdb", "pib_duckdb"}
    assert agendamento.cron_schedule == "30 20 * * *"


@pytest.mark.parametrize("check", TODOS_OS_CHECKS, ids=lambda c: c.node_def.name)
def test_toda_fonte_em_dia_cumpre_o_sla(banco_em_dia, check):
    res = check(build_asset_check_context())

    assert res.passed, res.description
    assert "sla_declarado" in res.metadata


@pytest.mark.parametrize("check", TODOS_OS_CHECKS, ids=lambda c: c.node_def.name)
def test_toda_fonte_sem_tabela_vira_erro_e_nao_excecao(tmp_path, monkeypatch, check):
    """Fonte cuja carga ainda não rodou: o check acusa, não quebra a execução."""
    caminho = tmp_path / "vazio.duckdb"
    duckdb.connect(str(caminho)).close()
    monkeypatch.setattr(checks, "DB_PADRAO", caminho)

    res = check(build_asset_check_context())

    assert not res.passed
    assert res.severity == AssetCheckSeverity.ERROR


@pytest.mark.parametrize(
    ("check", "atraso_dias"),
    [
        (check_ipca_freshness_e_volume, 120),
        (check_salario_minimo_freshness_e_volume, 120),
        (check_pib_freshness_e_volume, 400),
        (check_pib_internacional_freshness_e_volume, 1200),
        (check_clima_estacoes_freshness_e_volume, 30),
        (check_commodities_freshness_e_volume, 120),
    ],
    ids=lambda v: v.node_def.name if hasattr(v, "node_def") else str(v),
)
def test_fonte_atrasada_alerta_mas_nao_e_erro(tmp_path, monkeypatch, check, atraso_dias):
    caminho = tmp_path / "atrasado.duckdb"
    _banco(caminho, date.today() - timedelta(days=atraso_dias))
    monkeypatch.setattr(checks, "DB_PADRAO", caminho)

    res = check(build_asset_check_context())

    assert not res.passed
    assert res.severity == AssetCheckSeverity.WARN  # volume em ordem: só o atraso pesa


def test_commodities_aponta_a_serie_atrasada(tmp_path, monkeypatch):
    """A série diária parada acusa; a mensal, com a mesma idade, ainda está dentro do SLA."""
    caminho = tmp_path / "commodities.duckdb"
    hoje = date.today()
    with duckdb.connect(str(caminho)) as con:
        con.execute("create schema bronze")
        con.execute(
            "create table bronze.commodities_cotacao as "
            "select 'WTI' as symbol, 'daily' as intervalo, (?::date - i::int) as data_referencia "
            "from range(150) t(i) "
            "union all "
            "select 'COPPER', 'monthly', (?::date - i::int * 30) from range(24) t(i)",
            [hoje - timedelta(days=30), hoje - timedelta(days=30)],
        )
    monkeypatch.setattr(checks, "DB_PADRAO", caminho)

    res = check_commodities_freshness_e_volume(build_asset_check_context())

    assert not res.passed
    assert "WTI" in res.metadata["series_atrasadas"].value
    assert "COPPER" not in res.metadata["series_atrasadas"].value
