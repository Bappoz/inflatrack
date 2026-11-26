"""Aplicação do modelo: a variação prevista de cada subitem em cada praça no mês seguinte ao
último IPCA divulgado, com o erro típico para o site mostrar uma faixa.

Decisão do ponto de parada (`docs/evidencias/e4/avaliacao_todas_pracas.md`): XGBoost fixo, sem
clima, um modelo só para todas as praças. Usado pelo modelo do dbt
`dbt/models/predicao/fct_previsao_subitem.py`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from inflatrack.predicao.modelos import prever_xgboost, treinar_xgboost
from inflatrack.predicao.serie import FEATURES_BASE
from inflatrack.predicao.walk_forward import avaliar, metricas, origens_de_teste

MODELO = "xgboost_sem_clima"
_UM_MES = pd.DateOffset(months=1)
_COLUNAS = [
    "codigo_localidade",
    "codigo_subitem",
    "mes_base",
    "mes_previsto",
    "variacao_prevista_pct",
    "erro_tipico_pct",
    "gerado_em",
]


def prever_proximo_mes(base: pd.DataFrame) -> pd.DataFrame:
    """Treina com tudo o que tem alvo conhecido (mês <= último IPCA − 1) e prevê o mês seguinte
    ao último IPCA para cada série que tem esse IPCA."""
    mes_base = base.loc[base["y"].notna(), "mes"].max()
    atuais = base[(base["mes"] == mes_base) & base["y"].notna()]
    treino = base[(base["mes"] <= mes_base - _UM_MES) & base["alvo"].notna()]
    modelo = treinar_xgboost(treino, FEATURES_BASE)
    return pd.DataFrame(
        {
            "codigo_localidade": atuais["codigo_localidade"].astype(int).to_numpy(),
            "codigo_subitem": atuais["codigo_subitem"].astype(str).to_numpy(),
            "mes_base": mes_base,
            "mes_previsto": mes_base + _UM_MES,
            "variacao_prevista_pct": np.asarray(
                prever_xgboost(modelo, atuais, FEATURES_BASE), dtype=float
            ),
        }
    )


def erro_tipico(base: pd.DataFrame, meses: int = 12) -> pd.DataFrame:
    """MAE do XGBoost por subitem (juntando as praças) num walk-forward dos últimos `meses`
    meses. Subitem sem previsão na janela fica com o MAE do grupo do IPCA (1º dígito) e, sem
    ele, com o MAE geral."""
    previsoes = avaliar(base, origens_de_teste(base, meses), modelos=(MODELO,))
    previsoes = previsoes.dropna(subset=["previsto"])
    previsoes["grupo_ipca"] = previsoes["codigo_subitem"].str[0]
    por_subitem = metricas(previsoes, por=["codigo_subitem"]).set_index("codigo_subitem")["mae"]
    por_grupo = metricas(previsoes, por=["grupo_ipca"]).set_index("grupo_ipca")["mae"]
    geral = float((previsoes["previsto"] - previsoes["real"]).abs().mean())

    codigos = pd.Series(sorted(base["codigo_subitem"].astype(str).unique()))
    erro = codigos.map(por_subitem)
    erro = erro.fillna(codigos.str[0].map(por_grupo)).fillna(geral)
    return pd.DataFrame({"codigo_subitem": codigos, "erro_tipico_pct": erro.astype(float)})


def tabela_previsao(base: pd.DataFrame, gerado_em: pd.Timestamp) -> pd.DataFrame:
    """A tabela `gold.fct_previsao_subitem`: uma linha por praça e subitem."""
    tabela = prever_proximo_mes(base).merge(erro_tipico(base), on="codigo_subitem", how="left")
    tabela["gerado_em"] = gerado_em
    return (
        tabela[_COLUNAS].sort_values(["codigo_localidade", "codigo_subitem"]).reset_index(drop=True)
    )
