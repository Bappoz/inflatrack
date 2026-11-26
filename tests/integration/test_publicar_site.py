"""Publicação no Supabase, ensaiada no Postgres local num schema temporário. Precisa de `just up`.

Tudo numa transação desfeita no fim: o schema, os papéis `anon` e `authenticated` (que no
Supabase já existem) e os dados somem.
"""

from pathlib import Path

import pandas as pd
import psycopg
import pytest

from inflatrack.common.db import dsn_do_ambiente
from inflatrack.reverse_etl.publicar_site import Publicacao, gravar

MIGRATIONS = Path(__file__).resolve().parents[2] / "web" / "backend" / "migrations"
MIGRATION = MIGRATIONS / "003_publicacao_inflatrack.sql"
MIGRATION_DASHBOARD = MIGRATIONS / "004_dashboard_localidade.sql"


@pytest.fixture
def supabase():
    try:
        conexao = psycopg.connect(dsn_do_ambiente(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres fora do ar")
    with conexao:
        conexao.execute(
            "do $$ begin"
            " if not exists (select from pg_roles where rolname = 'anon') then"
            "   create role anon nologin; end if;"
            " if not exists (select from pg_roles where rolname = 'authenticated') then"
            "   create role authenticated nologin; end if;"
            " end $$"
        )
        conexao.execute("create schema teste_supabase")
        conexao.execute("grant usage on schema teste_supabase to anon, authenticated")
        conexao.execute("set local search_path to teste_supabase")
        conexao.execute(MIGRATION.read_text(encoding="utf-8"))
        conexao.execute(MIGRATION_DASHBOARD.read_text(encoding="utf-8"))
        yield conexao
        conexao.rollback()


def _publicacao(variacao: float = 0.5, painel_ok: bool = True) -> Publicacao:
    agora = pd.Timestamp("2026-11-19 12:00", tz="UTC")
    return Publicacao(
        previsao=pd.DataFrame(
            {
                "codigo_localidade": [1, 3501],
                "codigo_subitem": ["1101002", "1101002"],
                "mes_base": [pd.Timestamp("2026-10-01")] * 2,
                "mes_previsto": [pd.Timestamp("2026-11-01")] * 2,
                "variacao_prevista_pct": [variacao, variacao + 1],
                "erro_tipico_pct": [1.9, 1.9],
                "gerado_em": [agora] * 2,
            }
        ),
        subitem=pd.DataFrame(
            {
                "codigo_subitem": ["1101002"],
                "nome": ["Arroz"],
                "codigo_grupo": ["1"],
                "nome_grupo": ["Alimentação e bebidas"],
            }
        ),
        uf_praca=pd.DataFrame(
            {
                "uf": ["SP", "TO"],
                "codigo_localidade": [3501, 1],
                "nome_praca": ["São Paulo", "Brasil"],
            }
        ),
        resumo=pd.DataFrame(
            {
                "codigo_localidade": [1],
                "codigo_subitem": ["1101002"],
                "mes_referencia": [pd.Timestamp("2026-10-01")],
                "variacao_mensal_pct": [3.1],
                "variacao_12m_pct": [10.2],
            }
        ),
        painel=[
            {
                "id": "p1",
                "titulo": "Inflação por setor",
                "grafico": "bar",
                "eixo_x": "setor",
                "eixo_y": ["pct"],
                "linhas": [{"setor": "Alimentação", "pct": 4.5}] if painel_ok else None,
                "ate_o_mes": "10/2026",
            }
        ],
        dashboard={
            1: {"latest_month": "2026-10-01", "kpis": {"ipca_12m_pct": 4.5}, "history": []},
            3501: {"latest_month": "2026-10-01", "kpis": {"ipca_12m_pct": 4.8}, "history": []},
        },
    )


def _contar(conexao, tabela: str) -> int:
    return conexao.execute(f"select count(*) from {tabela}").fetchone()[0]


def test_publicar_duas_vezes_nao_dobra_as_linhas(supabase) -> None:
    gravar(supabase, _publicacao())
    contagem = gravar(supabase, _publicacao(variacao=0.7))

    assert contagem == {
        "previsao_subitem": 2,
        "subitem": 1,
        "uf_praca": 2,
        "resumo_subitem": 1,
        "painel_grafico": 1,
        "dashboard_localidade": 2,
    }
    assert _contar(supabase, "previsao_subitem") == 2
    (valor,) = supabase.execute(
        "select variacao_prevista_pct from previsao_subitem where codigo_localidade = 1"
    ).fetchone()
    assert valor == pytest.approx(0.7)


def test_erro_no_meio_mantem_a_publicacao_anterior(supabase) -> None:
    gravar(supabase, _publicacao())

    with pytest.raises(psycopg.Error):
        gravar(supabase, _publicacao(variacao=9.9, painel_ok=False))

    (valor,) = supabase.execute(
        "select variacao_prevista_pct from previsao_subitem where codigo_localidade = 1"
    ).fetchone()
    assert valor == pytest.approx(0.5)
    assert _contar(supabase, "painel_grafico") == 1
    assert _contar(supabase, "dashboard_localidade") == 2


def test_anon_le_e_nao_escreve(supabase) -> None:
    gravar(supabase, _publicacao())
    supabase.execute("set local role anon")

    assert _contar(supabase, "previsao_subitem") == 2
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        supabase.execute("delete from previsao_subitem")


def test_dashboard_da_praca_volta_como_foi_publicado(supabase) -> None:
    gravar(supabase, _publicacao())

    (dados,) = supabase.execute(
        "select dados from dashboard_localidade where codigo_localidade = 3501"
    ).fetchone()
    assert dados["kpis"] == {"ipca_12m_pct": 4.8}


@pytest.mark.parametrize(
    "esvaziar",
    ["previsao", "painel", "dashboard", "dashboard-sem-brasil"],
    ids=["sem-previsao", "grafico-vazio", "sem-dashboard", "dashboard-sem-brasil"],
)
def test_publicacao_vazia_e_recusada_antes_de_apagar(supabase, esvaziar: str) -> None:
    """Gold ou serie vazias (clone novo antes do analitico_job) não podem apagar o site."""
    gravar(supabase, _publicacao())
    vazia = _publicacao()
    if esvaziar == "previsao":
        vazia.previsao = vazia.previsao.iloc[0:0]
    elif esvaziar == "painel":
        vazia.painel[0]["linhas"] = []
    elif esvaziar == "dashboard":
        vazia.dashboard = {}
    else:
        del vazia.dashboard[1]

    with pytest.raises(ValueError, match="vazi"):
        gravar(supabase, vazia)

    assert _contar(supabase, "previsao_subitem") == 2
    assert _contar(supabase, "painel_grafico") == 1
    assert _contar(supabase, "dashboard_localidade") == 2
