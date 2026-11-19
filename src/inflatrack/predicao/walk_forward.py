"""Validação walk-forward (Seção 2.4, Regra 3): a cada mês de teste, tudo é refeito só com o
que se sabia naquele mês, e prevê-se o mês seguinte.

Na origem t, o IPCA de t acabou de sair. Uma linha de treino de mês s tem alvo s+1, que só é
conhecido se s+1 <= t; por isso o XGBoost treina com as linhas de mês <= t-1. As regressões usam
os últimos `janela` meses do índice até t; as ingênuas repetem t ou o mesmo mês do ano anterior.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from inflatrack.predicao.modelos import (
    indice_encadeado,
    prever_linear,
    prever_logaritmica,
    prever_xgboost,
    treinar_xgboost,
)
from inflatrack.predicao.serie import FEATURES_BASE, FEATURES_CLIMA

MODELOS = (
    "ingenua",
    "ingenua_sazonal",
    "linear",
    "logaritmica",
    "xgboost_sem_clima",
    "xgboost_com_clima",
)
_VARIANTES_XGBOOST = {
    "xgboost_sem_clima": FEATURES_BASE,
    "xgboost_com_clima": FEATURES_BASE + FEATURES_CLIMA,
}
_UM_MES = pd.DateOffset(months=1)


def origens_de_teste(base: pd.DataFrame, meses: int = 36) -> list[pd.Timestamp]:
    """Os últimos `meses` meses cujo alvo (o mês seguinte) já foi divulgado."""
    com_alvo = sorted(base.loc[base["alvo"].notna(), "mes"].unique())
    return [pd.Timestamp(m) for m in com_alvo[-meses:]]


def avaliar(base: pd.DataFrame, origens: list[pd.Timestamp], janela: int = 24) -> pd.DataFrame:
    """Uma linha por subitem x origem x modelo: previsto e real da variação em t+1."""
    y_por_chave = base.set_index(["codigo_subitem", "mes"])["y"]
    partes = []
    for origem in origens:
        alvo = base[(base["mes"] == origem) & base["alvo"].notna()]
        if alvo.empty:
            continue
        previsoes = {
            "ingenua": alvo["y"].to_numpy(dtype=float),
            "ingenua_sazonal": _sazonal(y_por_chave, alvo),
            **_regressoes(base, alvo, origem, janela),
        }
        treino = base[(base["mes"] <= origem - _UM_MES) & base["alvo"].notna()]
        for nome, colunas in _VARIANTES_XGBOOST.items():
            modelo = treinar_xgboost(treino, colunas)
            previsoes[nome] = np.asarray(prever_xgboost(modelo, alvo, colunas), dtype=float)
        for nome in MODELOS:
            partes.append(
                pd.DataFrame(
                    {
                        "codigo_subitem": alvo["codigo_subitem"].astype(str).to_numpy(),
                        "grupo": alvo["grupo"].astype(str).to_numpy(),
                        "mes": origem,
                        "mes_alvo": origem + _UM_MES,
                        "modelo": nome,
                        "previsto": previsoes[nome],
                        "real": alvo["alvo"].to_numpy(dtype=float),
                    }
                )
            )
    return pd.concat(partes, ignore_index=True)


def _sazonal(y_por_chave: pd.Series, alvo: pd.DataFrame) -> np.ndarray:
    """O mesmo mês do ano anterior ao alvo: mes_alvo - 12 = t - 11."""
    chaves = list(zip(alvo["codigo_subitem"], alvo["mes"] - pd.DateOffset(months=11), strict=True))
    return y_por_chave.reindex(chaves).to_numpy(dtype=float)


def _regressoes(
    base: pd.DataFrame, alvo: pd.DataFrame, origem: pd.Timestamp, janela: int
) -> dict[str, np.ndarray]:
    inicio = origem - pd.DateOffset(months=janela - 1)
    recorte = base[(base["mes"] >= inicio) & (base["mes"] <= origem)]
    linear, logaritmica = [], []
    for codigo in alvo["codigo_subitem"]:
        variacoes = recorte.loc[recorte["codigo_subitem"] == codigo, "y"].to_numpy(dtype=float)
        if variacoes.size < janela:
            linear.append(np.nan)
            logaritmica.append(np.nan)
            continue
        indice = indice_encadeado(variacoes)
        linear.append(prever_linear(indice))
        logaritmica.append(prever_logaritmica(indice))
    return {"linear": np.array(linear), "logaritmica": np.array(logaritmica)}


def metricas(previsoes: pd.DataFrame, por: list[str] | None = None) -> pd.DataFrame:
    """MAE, RMSE (pontos percentuais), n e ganho sobre a ingênua (`1 - MAE / MAE_ingênua`).

    Só entram as linhas (subitem, mês-alvo) em que todos os modelos previram: comparar um modelo
    em 36 meses com outro em 24 favoreceria quem pula os meses difíceis.
    """
    por = list(por or [])
    chave = ["codigo_subitem", "mes_alvo"]
    modelos = previsoes["modelo"].nunique()
    completas = previsoes.dropna(subset=["previsto"]).groupby(chave)["modelo"].nunique().eq(modelos)
    validas = previsoes.set_index(chave).loc[completas[completas].index].reset_index()
    erro = validas["previsto"] - validas["real"]
    validas = validas.assign(abs_erro=erro.abs(), quad_erro=erro**2)
    tabela = (
        validas.groupby([*por, "modelo"], observed=True)
        .agg(mae=("abs_erro", "mean"), quad=("quad_erro", "mean"), n=("abs_erro", "size"))
        .reset_index()
    )
    tabela["rmse"] = np.sqrt(tabela.pop("quad"))
    ingenua = tabela.loc[tabela["modelo"] == "ingenua", [*por, "mae"]]
    if por:
        tabela = tabela.merge(ingenua.rename(columns={"mae": "mae_ingenua"}), on=por, how="left")
    else:
        tabela["mae_ingenua"] = ingenua["mae"].squeeze() if not ingenua.empty else np.nan
    tabela["ganho_sobre_ingenua"] = 1 - tabela["mae"] / tabela.pop("mae_ingenua")
    return tabela[[*por, "modelo", "mae", "rmse", "n", "ganho_sobre_ingenua"]]
