import math

import numpy as np
import pandas as pd
import pytest

from inflatrack.predicao.modelos import (
    indice_encadeado,
    prever_linear,
    prever_logaritmica,
    prever_xgboost,
    treinar_xgboost,
)

T = np.arange(1, 25, dtype=float)


def test_indice_encadeado_comeca_em_100_e_compoe() -> None:
    assert indice_encadeado(np.array([1.0, 2.0])) == pytest.approx([101.0, 103.02])


def test_indice_propaga_nulo() -> None:
    assert math.isnan(indice_encadeado(np.array([1.0, np.nan, 2.0]))[-1])


def test_regressao_linear_acerta_uma_reta() -> None:
    indice = 10 + 2 * T

    esperado = ((10 + 2 * 25) / (10 + 2 * 24) - 1) * 100
    assert prever_linear(indice) == pytest.approx(esperado)


def test_regressao_logaritmica_acerta_a_curva() -> None:
    indice = 5 + 3 * np.log(T)

    esperado = ((5 + 3 * np.log(25)) / (5 + 3 * np.log(24)) - 1) * 100
    assert prever_logaritmica(indice) == pytest.approx(esperado)


@pytest.mark.parametrize("prever", [prever_linear, prever_logaritmica])
def test_regressao_com_buraco_na_janela_nao_preve(prever) -> None:
    indice = 10 + 2 * T
    indice[5] = np.nan

    assert math.isnan(prever(indice))


def _dados(n: int = 200) -> pd.DataFrame:
    gerador = np.random.default_rng(0)
    x = gerador.uniform(-1, 1, n)
    return pd.DataFrame(
        {"x": x, "cat": pd.Categorical(gerador.choice(["a", "b"], n)), "alvo": 2 * x}
    )


def test_xgboost_aprende_e_e_deterministico() -> None:
    dados = _dados()
    colunas = ["x", "cat"]

    primeira = prever_xgboost(treinar_xgboost(dados, colunas), dados, colunas)
    segunda = prever_xgboost(treinar_xgboost(dados, colunas), dados, colunas)

    assert np.abs(primeira - dados["alvo"]).mean() < 0.5
    assert np.array_equal(primeira, segunda)
