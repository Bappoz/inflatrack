"""Cliente HTTP do Open-Meteo (https://open-meteo.com), usado como clima PROVISÓRIO.

O INMET publica as medições no pacote anual do BDMEP cerca de 1×/mês. Entre o último dia
publicado e ontem, o clima vem do Open-Meteo: valores de modelo em grade (ERA5 com ~5 dias de
atraso, completado pela análise e previsão do ECMWF IFS), não de estação. A temperatura fica
perto da medida; a chuva de um ponto pode divergir bastante (ver docs/fontes/clima.md).

Plano gratuito: sem chave, uso não comercial, licença CC BY 4.0 (citar "Weather data by
Open-Meteo.com"), até 10 mil chamadas por dia. Uma coleta faz UMA chamada para todas as
estações (coordenadas separadas por vírgula).

Este módulo só fala com a internet; gravar em Delta é da Bronze (``inflatrack.bronze.clima``).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger("inflatrack.open_meteo")

URL_ARQUIVO = "https://archive-api.open-meteo.com/v1/archive"
ATRIBUICAO = "Weather data by Open-Meteo.com (CC BY 4.0)"

# Nome no Open-Meteo -> coluna da Bronze (as mesmas de clima_medicao).
VARIAVEIS_DIARIAS = {
    "temperature_2m_mean": "temp_media",
    "temperature_2m_max": "temp_max",
    "temperature_2m_min": "temp_min",
    "precipitation_sum": "precipitacao_total_mm",
    "relative_humidity_2m_mean": "umidade_relativa_media_pct",
    "relative_humidity_2m_min": "umidade_relativa_min_pct",
}


class OpenMeteoError(ValueError):
    """Resposta inválida ou erro na API do Open-Meteo."""


def parametros_diarios(
    coordenadas: Sequence[tuple[float, float]], inicio: date, fim: date
) -> dict[str, str]:
    """Parâmetros da consulta diária. ``timezone=GMT``: o dia é UTC, como no BDMEP."""
    return {
        "latitude": ",".join(f"{lat:.5f}" for lat, _ in coordenadas),
        "longitude": ",".join(f"{lon:.5f}" for _, lon in coordenadas),
        "start_date": inicio.isoformat(),
        "end_date": fim.isoformat(),
        "daily": ",".join(VARIAVEIS_DIARIAS),
        "timezone": "GMT",
    }


class OpenMeteoClient:
    def __init__(self, cliente_http: httpx.Client | None = None) -> None:
        self._cliente = cliente_http
        self.headers = {"User-Agent": "InflaTrack/1.0 (Weather Ingestion Pipeline)"}

    def buscar_diario(
        self, coordenadas: Sequence[tuple[float, float]], inicio: date, fim: date
    ) -> tuple[str, str]:
        """Consulta o dia a dia de várias coordenadas numa chamada; devolve (URL, corpo JSON)."""
        if not coordenadas:
            raise OpenMeteoError("Informe ao menos uma coordenada.")
        params = parametros_diarios(coordenadas, inicio, fim)
        if self._cliente is not None:
            resposta = self._cliente.get(URL_ARQUIVO, params=params, headers=self.headers)
        else:
            with httpx.Client(timeout=60.0) as cliente:
                resposta = cliente.get(URL_ARQUIVO, params=params, headers=self.headers)
        if resposta.status_code >= 400:
            raise OpenMeteoError(
                f"Open-Meteo respondeu {resposta.status_code}: {resposta.text[:300]}"
            )
        return str(resposta.url), resposta.text


def transformar_diario(payload: Any, estacoes: Sequence[str]) -> list[dict]:
    """Uma linha por estação x dia, na ordem das coordenadas pedidas.

    Com uma coordenada o Open-Meteo devolve um objeto; com várias, uma lista na mesma ordem.
    Dia sem nenhuma variável (fora do alcance do modelo) não vira linha.
    """
    blocos = payload if isinstance(payload, list) else [payload]
    if len(blocos) != len(estacoes):
        raise OpenMeteoError(
            f"Open-Meteo devolveu {len(blocos)} locais para {len(estacoes)} estações"
        )
    linhas = []
    for estacao_id, bloco in zip(estacoes, blocos, strict=True):
        diario = bloco.get("daily") if isinstance(bloco, dict) else None
        if not isinstance(diario, dict) or "time" not in diario:
            raise OpenMeteoError(f"Resposta sem 'daily.time' para a estação {estacao_id}")
        faltando = [nome for nome in VARIAVEIS_DIARIAS if nome not in diario]
        if faltando:
            raise OpenMeteoError(f"Resposta sem as variáveis {faltando} ({estacao_id})")
        for indice, dia in enumerate(diario["time"]):
            valores = {
                coluna: _numero(diario[nome][indice]) for nome, coluna in VARIAVEIS_DIARIAS.items()
            }
            if all(valor is None for valor in valores.values()):
                continue
            linhas.append(
                {
                    "estacao_id": estacao_id,
                    "data_referencia": date.fromisoformat(dia),
                    **valores,
                    "latitude_grade": _numero(bloco.get("latitude")),
                    "longitude_grade": _numero(bloco.get("longitude")),
                }
            )
    return linhas


def _numero(valor: Any) -> float | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None
