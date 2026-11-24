"""SPI-3: Índice de Precipitação Padronizado de 3 meses, sem vazamento do futuro.

Método de McKee et al. (1993), o do guia da OMM (WMO-No. 1090): a chuva acumulada em 3 meses de
uma estação, para cada mês do calendário, segue uma distribuição gama; o SPI é o quantil da normal
padrão com a mesma probabilidade acumulada. SPI -1 é "seca moderada", -1,5 "severa", -2
"extrema"; positivo é excesso de chuva.

Diferença deliberada do guia: a gama de um ano é ajustada só com os ANOS ANTERIORES do mesmo mês
do calendário (no mínimo ``ANOS_MINIMOS``), como as normais de ``int_clima__anomalia_mensal``. O
guia usa um período fixo de 30 anos, que incluiria anos futuros e vazaria informação para o
treino walk-forward do modelo preditivo. Com a série desde 2006, o SPI começa por volta de 2016.

A gama usa a aproximação de máxima verossimilhança de Thom (1958), a mesma do guia. Totais zero
entram pela probabilidade ``q`` de zero: H(x) = q + (1 - q) G(x).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

ANOS_MINIMOS = 10
JANELA_MESES = 3
# Corta a probabilidade em ±3 desvios: com 10 a 20 anos de referência, um quantil além disso é
# extrapolação da cauda da gama, não informação.
PROBABILIDADE_MINIMA = stats.norm.cdf(-3.0)
PROBABILIDADE_MAXIMA = stats.norm.cdf(3.0)


@dataclass(frozen=True)
class Gama:
    """Gama mista: probabilidade de zero e parâmetros de forma e escala dos totais positivos."""

    q_zero: float
    forma: float
    escala: float


def ajustar_gama(referencia: Sequence[float]) -> Gama | None:
    """Ajusta a gama aos totais de referência. ``None`` se não há anos suficientes."""
    valores = np.asarray([v for v in referencia if v is not None and not math.isnan(v)], float)
    if len(valores) < ANOS_MINIMOS:
        return None
    positivos = valores[valores > 0]
    if len(positivos) < 3:
        return None  # quase sempre seco: a gama dos positivos não tem como ser estimada
    media = positivos.mean()
    a = math.log(media) - np.log(positivos).mean()
    if a <= 0:
        return None  # todos os positivos iguais: sem dispersão para ajustar
    forma = (1 + math.sqrt(1 + 4 * a / 3)) / (4 * a)
    return Gama(
        q_zero=1 - len(positivos) / len(valores),
        forma=forma,
        escala=media / forma,
    )


def spi(valor: float | None, referencia: Sequence[float]) -> float | None:
    """SPI de ``valor`` contra a gama ajustada em ``referencia`` (só anos anteriores)."""
    if valor is None or math.isnan(valor):
        return None
    gama = ajustar_gama(referencia)
    if gama is None:
        return None
    acumulada = 0.0 if valor <= 0 else stats.gamma.cdf(valor, gama.forma, scale=gama.escala)
    probabilidade = gama.q_zero + (1 - gama.q_zero) * acumulada
    probabilidade = min(max(probabilidade, PROBABILIDADE_MINIMA), PROBABILIDADE_MAXIMA)
    return float(stats.norm.ppf(probabilidade))


def spi_3_meses(mensal: pd.DataFrame) -> pd.DataFrame:
    """SPI-3 de cada estação x mês a partir da chuva mensal da Silver.

    ``mensal`` precisa de ``estacao_id``, ``mes_referencia`` e ``precipitacao_total_mm``, com a
    grade de meses completa por estação (é o caso de ``int_clima__anomalia_mensal``). O total de
    3 meses só existe se os 3 meses tiverem chuva válida; mês sem chuva válida quebra a janela.
    """
    dados = mensal[["estacao_id", "mes_referencia", "precipitacao_total_mm"]].copy()
    dados["mes_referencia"] = pd.to_datetime(dados["mes_referencia"])
    dados["precipitacao_total_mm"] = pd.to_numeric(dados["precipitacao_total_mm"], errors="coerce")
    dados = dados.sort_values(["estacao_id", "mes_referencia"]).reset_index(drop=True)
    dados["precipitacao_3m_mm"] = (
        dados.groupby("estacao_id")["precipitacao_total_mm"]
        .transform(lambda serie: serie.rolling(JANELA_MESES, min_periods=JANELA_MESES).sum())
        .round(3)
    )

    dados["spi_3"] = np.nan
    dados["anos_referencia_spi"] = 0
    dados["mes_do_ano"] = dados["mes_referencia"].dt.month
    for _, grupo in dados.groupby(["estacao_id", "mes_do_ano"], sort=False):
        anteriores: list[float] = []
        for indice, total in zip(grupo.index, grupo["precipitacao_3m_mm"], strict=True):
            dados.at[indice, "anos_referencia_spi"] = len(anteriores)
            valor = spi(None if pd.isna(total) else float(total), anteriores)
            if valor is not None:
                dados.at[indice, "spi_3"] = valor
            if not pd.isna(total):
                anteriores.append(float(total))

    dados["mes_referencia"] = dados["mes_referencia"].dt.date
    return dados[
        ["estacao_id", "mes_referencia", "precipitacao_3m_mm", "spi_3", "anos_referencia_spi"]
    ]
