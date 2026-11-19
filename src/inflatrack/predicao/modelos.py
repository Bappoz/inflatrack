"""Os modelos comparados na avaliação.

As regressões linear e logarítmica são as linhas de tendência clássicas, ajustadas sobre o índice
de preços do subitem ao longo do tempo (`índice = a + b·t` e `índice = a + b·ln(t)`). Elas projetam
o índice do mês seguinte, e a previsão é a variação desse índice em %. O XGBoost prevê a variação
direto, a partir das variáveis da base (`serie.py`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb

# API nativa do xgboost (a do scikit-learn exigiria mais uma dependência). Equivale a
# XGBRegressor(max_depth=4, n_estimators=300, learning_rate=0.05, random_state=42).
PARAMETROS_XGBOOST = {
    "max_depth": 4,
    "eta": 0.05,
    "seed": 42,
    "tree_method": "hist",
    "objective": "reg:squarederror",
}
RODADAS_XGBOOST = 300


def indice_encadeado(variacoes_pct: np.ndarray) -> np.ndarray:
    """Base 100 antes do primeiro mês: [1 %, 2 %] -> [101, 103,02]. Um nulo contamina o resto."""
    return 100 * np.cumprod(1 + np.asarray(variacoes_pct, dtype=float) / 100)


def prever_linear(indice: np.ndarray) -> float:
    return _projetar(indice, lambda t: t)


def prever_logaritmica(indice: np.ndarray) -> float:
    return _projetar(indice, np.log)


def _projetar(indice: np.ndarray, transformar) -> float:
    """Ajusta `índice = a + b·f(t)` com t = 1..n e devolve a variação prevista para t = n+1."""
    indice = np.asarray(indice, dtype=float)
    if indice.size < 2 or np.isnan(indice).any():
        return float("nan")
    t = np.arange(1, indice.size + 1, dtype=float)
    b, a = np.polyfit(transformar(t), indice, 1)
    previsto = a + b * transformar(np.array(indice.size + 1, dtype=float))
    return float((previsto / indice[-1] - 1) * 100)


def treinar_xgboost(treino: pd.DataFrame, colunas: list[str]) -> xgb.Booster:
    dados = xgb.DMatrix(treino[colunas], label=treino["alvo"], enable_categorical=True)
    return xgb.train(PARAMETROS_XGBOOST, dados, num_boost_round=RODADAS_XGBOOST)


def prever_xgboost(modelo: xgb.Booster, linhas: pd.DataFrame, colunas: list[str]) -> np.ndarray:
    return modelo.predict(xgb.DMatrix(linhas[colunas], enable_categorical=True))
