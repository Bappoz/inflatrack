"""SPI-3 (McKee/OMM) só com anos anteriores: ajuste da gama, zeros, mínimo de anos e vazamento."""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from inflatrack.common import spi

REFERENCIA = [120.0, 80.0, 150.0, 95.0, 60.0, 200.0, 110.0, 130.0, 70.0, 140.0]


def test_ajuste_da_gama_segue_a_aproximacao_de_thom() -> None:
    gama = spi.ajustar_gama(REFERENCIA)

    a = math.log(np.mean(REFERENCIA)) - np.mean(np.log(REFERENCIA))
    forma = (1 + math.sqrt(1 + 4 * a / 3)) / (4 * a)
    assert gama.q_zero == 0
    assert gama.forma == pytest.approx(forma)
    assert gama.escala == pytest.approx(np.mean(REFERENCIA) / forma)


def test_spi_e_o_quantil_normal_da_probabilidade_gama() -> None:
    gama = spi.ajustar_gama(REFERENCIA)
    esperado = stats.norm.ppf(stats.gamma.cdf(50.0, gama.forma, scale=gama.escala))

    assert spi.spi(50.0, REFERENCIA) == pytest.approx(esperado)
    assert spi.spi(50.0, REFERENCIA) < -1  # bem abaixo do normal: seca
    assert spi.spi(np.median(REFERENCIA), REFERENCIA) == pytest.approx(0, abs=0.2)


def test_spi_cresce_com_a_chuva() -> None:
    valores = [spi.spi(x, REFERENCIA) for x in (40, 80, 120, 160, 240)]

    assert valores == sorted(valores)


def test_menos_de_dez_anos_de_referencia_nao_tem_spi() -> None:
    assert spi.spi(100.0, REFERENCIA[: spi.ANOS_MINIMOS - 1]) is None
    assert spi.spi(100.0, REFERENCIA) is not None


def test_zeros_entram_pela_probabilidade_de_zero() -> None:
    referencia = [0.0, 0.0] + REFERENCIA
    gama = spi.ajustar_gama(referencia)

    assert gama.q_zero == pytest.approx(2 / 12)
    assert spi.spi(0.0, referencia) == pytest.approx(stats.norm.ppf(2 / 12))


def test_extremos_ficam_limitados_a_tres_desvios() -> None:
    assert spi.spi(5000.0, REFERENCIA) == pytest.approx(3.0)
    assert spi.spi(0.0, REFERENCIA) == pytest.approx(-3.0)


def _serie(chuvas: dict[date, float | None]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "estacao_id": "A001",
            "mes_referencia": list(chuvas),
            "precipitacao_total_mm": list(chuvas.values()),
        }
    )


def _meses(anos: range, valor) -> dict[date, float | None]:
    return {date(a, m, 1): valor(a, m) for a in anos for m in range(1, 13)}


def test_spi_3_soma_tres_meses_e_compara_com_o_mesmo_mes_dos_anos_anteriores() -> None:
    rng = np.random.default_rng(7)
    chuvas = _meses(range(2006, 2020), lambda a, m: float(rng.gamma(2.0, 50.0)))
    saida = spi.spi_3_meses(_serie(chuvas)).set_index("mes_referencia")

    marco_2019 = saida.loc[date(2019, 3, 1)]
    # O total de 3 meses sai em mm com 3 casas, e é dele que o SPI parte.
    totais_marco = [
        round(sum(chuvas[date(a, m, 1)] for m in (1, 2, 3)), 3) for a in range(2006, 2020)
    ]
    assert marco_2019["precipitacao_3m_mm"] == pytest.approx(totais_marco[-1], abs=1e-9)
    assert marco_2019["anos_referencia_spi"] == 13
    assert marco_2019["spi_3"] == pytest.approx(spi.spi(totais_marco[-1], totais_marco[:-1]))
    # Com menos de 10 anos anteriores daquele mês ainda não há SPI.
    assert pd.isna(saida.loc[date(2015, 3, 1), "spi_3"])
    assert not pd.isna(saida.loc[date(2016, 3, 1), "spi_3"])


def test_spi_3_nao_usa_o_futuro() -> None:
    rng = np.random.default_rng(11)
    chuvas = _meses(range(2006, 2022), lambda a, m: float(rng.gamma(2.0, 50.0)))
    antes = spi.spi_3_meses(_serie(chuvas)).set_index("mes_referencia")["spi_3"]

    for mes in range(1, 13):
        chuvas[date(2021, mes, 1)] = 10_000.0  # um ano futuro absurdo
    depois = spi.spi_3_meses(_serie(chuvas)).set_index("mes_referencia")["spi_3"]

    passado = [d for d in antes.index if d < date(2021, 1, 1)]
    pd.testing.assert_series_equal(antes.loc[passado], depois.loc[passado])


def test_mes_sem_chuva_valida_quebra_a_janela_de_tres_meses() -> None:
    chuvas = _meses(range(2006, 2008), lambda a, m: 100.0)
    chuvas[date(2007, 5, 1)] = None
    saida = spi.spi_3_meses(_serie(chuvas)).set_index("mes_referencia")

    for mes in (5, 6, 7):
        assert pd.isna(saida.loc[date(2007, mes, 1), "precipitacao_3m_mm"])
    assert saida.loc[date(2007, 8, 1), "precipitacao_3m_mm"] == 300.0
