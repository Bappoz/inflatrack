"""Ponta a ponta (Nível 5): do HTML do DIEESE até a pergunta do painel, com o código real.

A cadeia percorre, sem simular nenhuma etapa do salário mínimo:

    HTML da fixture -> Bronze Delta -> loader -> bronze.* no DuckDB
        -> dbt (Silver e Gold) -> cópia para o Postgres -> consulta do painel

Só o IPCA é sintético: ``gold.fct_inflacao_mensal`` e ``gold.dim_calendario`` entram prontos,
com um índice conhecido, para que o resultado do dbt possa ser conferido contra uma conta feita
aqui, fora do SQL. Cada teste recalcula o esperado em Python a partir do HTML.

O dbt roda no arquivo temporário (``DBT_DUCKDB_PATH``) e escreve o ``target`` numa pasta
temporária, para não tocar no ``target/manifest.json`` que os testes do Dagster leem.
O teste da cópia para o Postgres usa um schema temporário e é pulado sem o Postgres no ar.
"""

import os
import subprocess
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import psycopg
import pytest

from inflatrack.bronze import salario_minimo
from inflatrack.common.db import dsn_do_ambiente
from inflatrack.reverse_etl import exportar_serie

RAIZ = Path(__file__).resolve().parents[2]
HTML = RAIZ / "tests" / "fixtures" / "salario_minimo" / "salario_minimo.html"
PERGUNTA_P3 = RAIZ / "scripts" / "sql" / "metabase" / "p3_salario_minimo_real.sql"

IPCA_12M_PCT = Decimal("6.0")
TAXA_MENSAL = Decimal("1.005")
INDICE_INICIAL = Decimal("1000")


def _indice(posicao: int) -> Decimal:
    return INDICE_INICIAL * TAXA_MENSAL**posicao


@pytest.fixture(scope="module")
def meses() -> list[dict]:
    """Os meses do DIEESE como o Bronze os extrai: o oráculo do teste."""
    return salario_minimo.transformar(HTML.read_text(encoding="utf-8", errors="replace"))


@pytest.fixture(scope="module")
def gold(tmp_path_factory, meses) -> Path:
    """Roda a cadeia inteira e devolve o DuckDB com a Gold pronta."""
    pasta = tmp_path_factory.mktemp("cadeia")
    banco = pasta / "analitico.duckdb"

    # 1. Bronze Delta e espelho no DuckDB, pelo código de produção.
    delta = pasta / "salario_minimo"
    salario_minimo.gravar(delta, HTML.read_text(encoding="utf-8", errors="replace"))
    assert salario_minimo.carregar_duckdb(delta, banco) == len(meses)

    # 2. O IPCA que a Gold de produção traria, com um índice conhecido.
    with duckdb.connect(str(banco)) as con:
        con.execute("CREATE SCHEMA IF NOT EXISTS gold")
        con.execute(
            "CREATE TABLE gold.dim_calendario AS SELECT mes_referencia FROM "
            "(SELECT unnest(generate_series(?::date, ?::date, INTERVAL 1 MONTH))::date "
            "AS mes_referencia)",
            [meses[0]["data_referencia"], meses[-1]["data_referencia"]],
        )
        con.execute(
            "CREATE TABLE gold.fct_inflacao_mensal (indice VARCHAR, nivel_categoria VARCHAR, "
            "codigo_localidade INTEGER, mes_referencia DATE, numero_indice DOUBLE, "
            "variacao_acum_12m_pct DOUBLE)"
        )
        for posicao, mes in enumerate(meses):
            con.execute(
                "INSERT INTO gold.fct_inflacao_mensal VALUES ('IPCA', 'geral', 1, ?, ?, ?)",
                [mes["data_referencia"], float(_indice(posicao)), float(IPCA_12M_PCT)],
            )

    # 3. Silver e Gold do salário mínimo, pelos modelos dbt reais (e seus testes). Em subprocesso:
    # o dbt-duckdb mantém o arquivo aberto no processo e travaria as leituras seguintes.
    resultado = subprocess.run(
        [
            sys.executable, "-c", "from dbt.cli.main import cli; cli()",
            "build",
            "--project-dir", str(RAIZ),
            "--profiles-dir", str(RAIZ),
            "--target-path", str(pasta / "dbt_target"),
            "--log-path", str(pasta / "dbt_logs"),
            "--select", "stg_salario_minimo__mes", "int_salario_minimo__mensal",
            "fct_salario_minimo_mensal",
        ],
        env={**os.environ, "DBT_DUCKDB_PATH": str(banco)},
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    assert resultado.returncode == 0, resultado.stdout[-3000:]
    return banco


def _linha(banco: Path, mes: date) -> dict:
    with duckdb.connect(str(banco), read_only=True) as con:
        cursor = con.execute(
            "SELECT * FROM gold.fct_salario_minimo_mensal WHERE mes_referencia = ?", [mes]
        )
        colunas = [c[0] for c in cursor.description]
        return dict(zip(colunas, cursor.fetchone(), strict=True))


def test_a_gold_tem_um_mes_do_diesse_por_linha(gold, meses) -> None:
    with duckdb.connect(str(gold), read_only=True) as con:
        total, primeiro, ultimo = con.execute(
            "SELECT count(*), min(mes_referencia), max(mes_referencia) "
            "FROM gold.fct_salario_minimo_mensal"
        ).fetchone()

    assert total == len(meses)
    assert (primeiro, ultimo) == (meses[0]["data_referencia"], meses[-1]["data_referencia"])


def test_salario_nominal_chega_igual_ao_html(gold, meses) -> None:
    for mes in (meses[0], meses[len(meses) // 2], meses[-1]):
        linha = _linha(gold, mes["data_referencia"])

        assert linha["salario_nominal"] == mes["salario_nominal"]
        assert linha["salario_necessario"] == mes["salario_necessario"]


def test_reajuste_e_ganho_real_em_12_meses_batem_com_a_conta_feita_fora_do_sql(gold, meses) -> None:
    posicao = len(meses) - 1
    atual, ha_12_meses = meses[posicao], meses[posicao - 12]
    reajuste = (atual["salario_nominal"] / ha_12_meses["salario_nominal"] - 1) * 100
    ganho_real = ((1 + reajuste / 100) / (1 + IPCA_12M_PCT / 100) - 1) * 100

    linha = _linha(gold, atual["data_referencia"])

    assert float(linha["variacao_nominal_12m_pct"]) == pytest.approx(float(reajuste), abs=1e-4)
    assert float(linha["ganho_real_12m_pct"]) == pytest.approx(float(ganho_real), abs=1e-4)


def test_os_12_primeiros_meses_nao_inventam_reajuste(gold, meses) -> None:
    for mes in meses[:12]:
        linha = _linha(gold, mes["data_referencia"])

        assert linha["variacao_nominal_12m_pct"] is None
        assert linha["ganho_real_12m_pct"] is None


def test_valor_corrigido_pelo_ipca_leva_tudo_para_reais_do_ultimo_mes(gold, meses) -> None:
    ultimo = len(meses) - 1
    for posicao in (0, ultimo // 2, ultimo):
        mes = meses[posicao]
        esperado = mes["salario_nominal"] * _indice(ultimo) / _indice(posicao)

        linha = _linha(gold, mes["data_referencia"])

        assert linha["mes_base_real"] == meses[-1]["data_referencia"]
        assert float(linha["salario_nominal_real"]) == pytest.approx(float(esperado), abs=0.01)
    assert (
        _linha(gold, meses[-1]["data_referencia"])["salario_nominal_real"]
        == meses[-1]["salario_nominal"]
    )


# --- Cópia para o Postgres e a pergunta do painel ---------------------------------------------


@pytest.fixture
def dsn() -> str:
    dsn = dsn_do_ambiente()
    try:
        psycopg.connect(dsn, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("Postgres fora do ar")
    return dsn


@pytest.fixture
def schema(dsn: str):
    nome = f"teste_e2e_{uuid.uuid4().hex[:8]}"
    yield nome
    with psycopg.connect(dsn, autocommit=True) as pg:
        pg.execute(f"DROP SCHEMA IF EXISTS {nome} CASCADE")


def test_a_pergunta_do_painel_devolve_o_que_a_gold_calculou(dsn, schema, gold) -> None:
    """Mesma métrica, mesmo valor: DuckDB (Gold), Postgres (`serie`) e a consulta do Metabase."""
    with exportar_serie.conectar(gold, dsn) as conexao:
        exportar_serie.exportar(conexao, ("fct_salario_minimo_mensal",), schema)
    # A consulta do painel lê `serie.`; aqui ela lê o schema temporário da cópia.
    consulta = PERGUNTA_P3.read_text(encoding="utf-8").replace("serie.", f"{schema}.")

    with psycopg.connect(dsn) as pg:
        painel = pg.execute(consulta).fetchall()
    with duckdb.connect(str(gold), read_only=True) as con:
        gold_linhas = con.execute(
            "SELECT mes_referencia, salario_nominal, salario_nominal_real, ganho_real_12m_pct "
            "FROM gold.fct_salario_minimo_mensal WHERE mes_referencia >= DATE '2006-01-01' "
            "ORDER BY mes_referencia"
        ).fetchall()

    assert len(painel) == len(gold_linhas) > 0
    assert painel == gold_linhas
