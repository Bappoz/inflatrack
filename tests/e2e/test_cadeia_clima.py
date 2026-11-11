"""Ponta a ponta (Nível 5): do pacote anual do BDMEP até a Gold do clima, com o código real.

    pacote .zip -> Raw e Bronze Delta -> loader -> bronze.clima_medicao no DuckDB
        -> dbt (staging, Silver mensal e gold.fct_clima_mensal)

Só o portal é falso (``ClienteBdmepFalso`` monta o .zip); o CSV tem o cabeçalho de um arquivo
real e valores escolhidos para que média, anomalia e lag possam ser conferidos fora do SQL.

Série de Brasília (A001, praça 5300108), janeiros de 2021 a 2024 com chuva de 0,1 mm/h e
temperatura 20, 21, 22 e 25 °C, mais dezembro de 2023 a 30 °C. Fevereiro de 2024 tem só 10 dias.
"""

import os
import subprocess
import sys
from calendar import monthrange
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from inflatrack.bronze import clima
from inflatrack.loaders import load_clima
from tests.clima_bdmep import ClienteBdmepFalso, csv_bdmep

RAIZ = Path(__file__).resolve().parents[2]
BRASILIA = 5300108
TEMPERATURA_JANEIRO = {2021: 20.0, 2022: 21.0, 2023: 22.0, 2024: 25.0}
CHUVA_HORA = 0.1


def _mes(ano: int, mes: int, temperatura: float, dias: int | None = None) -> dict:
    total = dias or monthrange(ano, mes)[1]
    return {date(ano, mes, dia): (temperatura, CHUVA_HORA) for dia in range(1, total + 1)}


def _pacotes() -> dict[int, dict[str, str]]:
    dias_por_ano: dict[int, dict] = {ano: _mes(ano, 1, t) for ano, t in TEMPERATURA_JANEIRO.items()}
    dias_por_ano[2023] |= _mes(2023, 12, 30.0)
    dias_por_ano[2024] |= _mes(2024, 2, 18.0, dias=10)
    return {ano: {"A001": csv_bdmep("A001", dias)} for ano, dias in dias_por_ano.items()}


@pytest.fixture(scope="module")
def gold(tmp_path_factory) -> Path:
    pasta = tmp_path_factory.mktemp("cadeia_clima")
    banco = pasta / "analitico.duckdb"
    delta = pasta / "clima"

    resumo = clima.processar_medicoes(
        ClienteBdmepFalso(_pacotes()), ["A001"], list(TEMPERATURA_JANEIRO), delta
    )
    assert resumo.falhas == []
    argumentos = ["--db", str(banco), "--delta-dir", str(delta), "--tabela", "medicao"]
    assert load_clima.main(argumentos) == 0

    # Em subprocesso: o dbt-duckdb mantém o arquivo aberto no processo e travaria as leituras.
    resultado = subprocess.run(
        [
            sys.executable, "-c", "from dbt.cli.main import cli; cli()",
            "build",
            "--project-dir", str(RAIZ),
            "--profiles-dir", str(RAIZ),
            "--target-path", str(pasta / "dbt_target"),
            "--log-path", str(pasta / "dbt_logs"),
            "--indirect-selection", "cautious",
            "--select", "+fct_clima_mensal", "assert_clima_valores_plausiveis",
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
            "SELECT * FROM gold.fct_clima_mensal WHERE codigo_localidade = ? "
            "AND mes_referencia = ?",
            [BRASILIA, mes],
        )
        colunas = [c[0] for c in cursor.description]
        return dict(zip(colunas, cursor.fetchone(), strict=True))


def test_grade_mensal_completa_entre_o_primeiro_e_o_ultimo_mes(gold) -> None:
    with duckdb.connect(str(gold), read_only=True) as con:
        total, primeiro, ultimo, pracas = con.execute(
            "SELECT count(*), min(mes_referencia), max(mes_referencia), "
            "count(DISTINCT codigo_localidade) FROM gold.fct_clima_mensal"
        ).fetchone()

    assert (primeiro, ultimo, pracas) == (date(2021, 1, 1), date(2024, 2, 1), 1)
    assert total == 38  # jan/2021 a fev/2024, sem buraco


def test_mes_sem_medicao_fica_nulo_e_nao_vira_seca(gold) -> None:
    linha = _linha(gold, date(2022, 6, 1))

    assert linha["dias_com_registro"] == 0
    assert linha["cobertura_dias"] == 0
    assert linha["temp_media"] is None
    assert linha["precipitacao_total_mm"] is None
    assert linha["dias_com_chuva"] is None


def test_janeiro_de_2024_media_chuva_e_anomalia_sem_vazamento(gold) -> None:
    linha = _linha(gold, date(2024, 1, 1))
    normal_anterior = sum(TEMPERATURA_JANEIRO[a] for a in (2021, 2022, 2023)) / 3

    assert linha["mes_fechado"] is True
    assert linha["cobertura_dias"] == 1
    assert linha["temp_media"] == Decimal("25.000")
    assert linha["temp_min_absoluta"] == Decimal("24.500")
    assert float(linha["precipitacao_total_mm"]) == pytest.approx(31 * 24 * CHUVA_HORA)
    assert linha["precipitacao_anomalia_mm"] == 0
    assert float(linha["temp_media_anomalia"]) == pytest.approx(25.0 - normal_anterior, abs=1e-3)
    # Lags são meses de calendário: t-1 é dezembro de 2023, t-2 (novembro) não tem dado.
    assert linha["temp_media_t_menos_1"] == Decimal("30.000")
    assert linha["temp_media_t_menos_2"] is None


def test_anomalia_exige_tres_anos_anteriores(gold) -> None:
    assert _linha(gold, date(2023, 1, 1))["temp_media_anomalia"] is None


def test_lag_da_anomalia_carrega_o_choque_para_o_mes_seguinte(gold) -> None:
    janeiro = _linha(gold, date(2024, 1, 1))
    fevereiro = _linha(gold, date(2024, 2, 1))

    assert fevereiro["temp_media_anomalia_t_menos_1"] == janeiro["temp_media_anomalia"]


def test_mes_com_poucos_dias_mantem_temperatura_e_anula_a_chuva(gold) -> None:
    fevereiro = _linha(gold, date(2024, 2, 1))

    assert fevereiro["dias_com_registro"] == 10
    assert fevereiro["mes_fechado"] is False  # a última leitura é 10/02/2024
    assert fevereiro["temp_media"] == Decimal("18.000")
    assert fevereiro["precipitacao_total_mm"] is None
