"""Cliente da API de dados meteorológicos do INMET e funções de transformação.

Consulta as estações meteorológicas e medições diárias (temperatura, precipitação
e umidade) para compor features climáticas no banco analítico.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger("inflatrack.inmet")

BASE_URL = "https://apitempo.inmet.gov.br"


class InmetError(ValueError):
    """Resposta inválida ou erro na API do INMET."""


class InmetClient:
    """Cliente HTTP com headers defensivos para o portal do INMET."""

    def __init__(self, cliente_http: httpx.Client | None = None) -> None:
        self._cliente = cliente_http
        self.headers = {"User-Agent": "InflaTrack/1.0 (Weather Ingestion Pipeline)"}

    def _get(self, endpoint: str, timeout: float = 30.0) -> Any:
        url = f"{BASE_URL}/{endpoint.lstrip('/')}"
        if self._cliente is not None:
            resposta = self._cliente.get(url, headers=self.headers, timeout=timeout)
            resposta.raise_for_status()
            return resposta.json()

        with httpx.Client() as client:
            resposta = client.get(url, headers=self.headers, timeout=timeout)
            resposta.raise_for_status()
            return resposta.json()

    def listar_estacoes(self, tipo: str = "T") -> list[dict[str, Any]]:
        """Busca o catálogo de estações do INMET (T=Todas, A=Automáticas, M=Manuais)."""
        payload = self._get(f"estacoes/{tipo}")
        if not isinstance(payload, list):
            raise InmetError(f"Formato inesperado ao listar estações: {type(payload)}")
        return payload

    def buscar_dados_estacao(
        self, estacao_id: str, data_inicio: str, data_fim: str
    ) -> list[dict[str, Any]]:
        """Busca as medições diárias de uma estação em um intervalo de datas."""
        payload = self._get(f"estacao/diaria/{data_inicio}/{data_fim}/{estacao_id}")
        if not isinstance(payload, list):
            raise InmetError(f"Formato inesperado ao buscar medições da estação {estacao_id}")
        return payload


def _para_float(valor: Any) -> float | None:
    if valor is None:
        return None
    try:
        return float(valor)
    except (ValueError, TypeError):
        return None


def transformar_estacoes(payload: list[dict[str, Any]]) -> pd.DataFrame:
    """Transforma a lista de estações da API em DataFrame estruturado."""
    registros: list[dict[str, Any]] = []

    for item in payload:
        if not isinstance(item, dict):
            continue
        estacao_id = item.get("CD_ESTACAO") or item.get("estacao_id")
        nome = item.get("DC_NOME") or item.get("nome")
        estado = item.get("SG_ESTADO") or item.get("estado")
        tipo = item.get("TP_ESTACAO") or item.get("tipo", "Automatica")

        if not estacao_id or not nome or not estado:
            continue

        registros.append(
            {
                "estacao_id": str(estacao_id).strip(),
                "nome": str(nome).strip(),
                "estado": str(estado).strip(),
                "tipo": str(tipo).strip(),
                "latitude": _para_float(item.get("VL_LATITUDE") or item.get("latitude")),
                "longitude": _para_float(item.get("VL_LONGITUDE") or item.get("longitude")),
                "altitude_m": _para_float(item.get("VL_ALTITUDE") or item.get("altitude_m")),
                "situacao": str(
                    item.get("CD_SITUACAO") or item.get("situacao", "Operante")
                ).strip(),
            }
        )

    if not registros:
        raise InmetError("Nenhuma estação válida pôde ser estruturada a partir do payload.")

    df = pd.DataFrame(registros)
    return (
        df.drop_duplicates(subset=["estacao_id"]).sort_values("estacao_id").reset_index(drop=True)
    )


def transformar_clima_diario(payload: list[dict[str, Any]]) -> pd.DataFrame:
    """Transforma medições diárias recebidas da API em DataFrame para a tabela clima_diario."""
    registros: list[dict[str, Any]] = []

    for item in payload:
        if not isinstance(item, dict):
            continue
        estacao_id = item.get("CD_ESTACAO") or item.get("estacao_id") or item.get("STATION_ID")
        data_medicao = (
            item.get("DT_MEDICAO")
            or item.get("data_referencia")
            or item.get("DATE")
            or str(item.get("DATETIME", ""))[:10]
        )

        if not estacao_id or not data_medicao:
            continue

        temp_min = _para_float(item.get("TEM_MIN") or item.get("temp_min") or item.get("MIN_TEMP"))
        temp_max = _para_float(item.get("TEM_MAX") or item.get("temp_max") or item.get("MAX_TEMP"))
        temp_med = _para_float(item.get("TEM_MED") or item.get("temp_media") or item.get("TEMP"))
        if temp_med is None and temp_min is not None and temp_max is not None:
            temp_med = round((temp_min + temp_max) / 2.0, 2)

        chuva = _para_float(
            item.get("CHUVA")
            or item.get("precipitacao_total_mm")
            or item.get("PRECIPITACAO_TOTAL")
            or item.get("RAIN")
        )
        if chuva is None:
            chuva = 0.0

        umd_med = _para_float(
            item.get("UMD_MED") or item.get("umidade_relativa_media_pct") or item.get("HUMI")
        )
        umd_min = _para_float(
            item.get("UMD_MIN") or item.get("umidade_relativa_min_pct") or item.get("MIN_RH")
        )
        observado = bool(item.get("observado", True))

        registros.append(
            {
                "estacao_id": str(estacao_id).strip(),
                "data_referencia": str(data_medicao)[:10],
                "temp_min": temp_min,
                "temp_max": temp_max,
                "temp_media": temp_med,
                "precipitacao_total_mm": chuva,
                "umidade_relativa_media_pct": umd_med,
                "umidade_relativa_min_pct": umd_min,
                "observado": observado,
            }
        )

    if not registros:
        raise InmetError(
            "Nenhuma medição climática válida pôde ser estruturada a partir do payload."
        )

    df = pd.DataFrame(registros)
    df["data_referencia"] = pd.to_datetime(df["data_referencia"]).dt.date
    return (
        df.drop_duplicates(subset=["estacao_id", "data_referencia"])
        .sort_values(["estacao_id", "data_referencia"])
        .reset_index(drop=True)
    )
