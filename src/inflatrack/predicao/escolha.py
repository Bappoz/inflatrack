"""Escolha de um modelo por subitem.

Para cada subitem, juntando as praças, vence o candidato de menor MAE nos meses da janela de
escolha. Quando o vencedor não consegue prever uma série (por exemplo, uma regressão sem 24 meses
seguidos naquela praça), a previsão usa a ingênua, que sempre prevê quando há o IPCA do mês.

`avaliar_escolha` mede a escolha honestamente: escolhe com os primeiros meses e mede só nos
seguintes, que a escolha não viu.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from inflatrack.predicao.walk_forward import metricas

RESERVA = "ingenua"
NOME = "escolha_por_subitem"
_CHAVE = ["codigo_localidade", "codigo_subitem", "mes_alvo"]


def escolher_por_subitem(previsoes: pd.DataFrame) -> pd.DataFrame:
    """`codigo_subitem`, `modelo` (o vencedor), `erro_tipico_pct` (o MAE dele) e
    `erro_ingenua_pct` (o MAE da reserva, para a linha que cair nela)."""
    por_subitem = metricas(previsoes, por=["codigo_subitem"])
    vencedores = por_subitem.loc[por_subitem.groupby("codigo_subitem")["mae"].idxmin()]
    ingenua = previsoes[previsoes["modelo"] == RESERVA].dropna(subset=["previsto"])
    erro_ingenua = (
        (ingenua["previsto"] - ingenua["real"]).abs().groupby(ingenua["codigo_subitem"]).mean()
    )
    escolha = vencedores.rename(columns={"mae": "erro_tipico_pct"})[
        ["codigo_subitem", "modelo", "erro_tipico_pct"]
    ]
    escolha["erro_ingenua_pct"] = escolha["codigo_subitem"].map(erro_ingenua)
    return escolha.reset_index(drop=True)


def aplicar_escolha(previsoes: pd.DataFrame, escolha: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por série e mês-alvo, com a previsão do modelo escolhido (ou da ingênua)."""
    base = previsoes[previsoes["modelo"] == RESERVA].drop(columns="modelo")
    base = base.rename(columns={"previsto": "previsto_reserva"})
    base["modelo_escolhido"] = base["codigo_subitem"].map(
        escolha.set_index("codigo_subitem")["modelo"]
    )
    escolhidas = previsoes[["modelo", *_CHAVE, "previsto"]].rename(
        columns={"modelo": "modelo_escolhido", "previsto": "previsto_escolhido"}
    )
    juntas = base.merge(escolhidas, on=["modelo_escolhido", *_CHAVE], how="left")
    usa_escolhido = juntas["previsto_escolhido"].notna()
    juntas["previsto"] = np.where(
        usa_escolhido, juntas["previsto_escolhido"], juntas["previsto_reserva"]
    )
    juntas["modelo_usado"] = np.where(usa_escolhido, juntas["modelo_escolhido"], RESERVA)
    juntas["modelo"] = NOME
    return juntas.drop(columns=["previsto_reserva", "previsto_escolhido", "modelo_escolhido"])


def avaliar_escolha(previsoes: pd.DataFrame, meses_escolha: int) -> pd.DataFrame:
    """Escolhe com os primeiros `meses_escolha` meses-alvo e devolve, só nos meses seguintes, os
    candidatos e a escolha por subitem, prontos para `metricas`."""
    meses = sorted(previsoes["mes_alvo"].unique())
    if len(meses) <= meses_escolha:
        raise ValueError(f"{len(meses)} meses não bastam para escolher com {meses_escolha}")
    corte = meses[meses_escolha]
    escolha = escolher_por_subitem(previsoes[previsoes["mes_alvo"] < corte])
    medicao = previsoes[previsoes["mes_alvo"] >= corte]
    return pd.concat([medicao, aplicar_escolha(medicao, escolha)], ignore_index=True)
