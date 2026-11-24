"""Clientes HTTP do INMET: catálogo de estações (API) e dados históricos (BDMEP).

O catálogo vem da API ``apitempo.inmet.gov.br``. As medições vêm dos pacotes anuais do BDMEP
(``portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip``, um CSV horário por estação): a rota
diária da API responde 404 e a horária só devolve 204 sem token desde 2026-10
(``docs/evidencias/e2/clima.md``). Este módulo só fala com a internet; ler o CSV e gravar em
Delta é da Bronze (``inflatrack.bronze.clima``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger("inflatrack.inmet")

BASE_URL = "https://apitempo.inmet.gov.br"
URL_DADOS_HISTORICOS = "https://portal.inmet.gov.br/uploads/dadoshistoricos"

# Um pacote anual tem de 15 a 90 MB: o limite de leitura vale por bloco, não pelo download todo.
TIMEOUT_ZIP = httpx.Timeout(30.0, read=120.0)


class InmetError(ValueError):
    """Resposta inválida ou erro na API do INMET."""


@dataclass(frozen=True)
class VersaoZip:
    """O que o portal diz do pacote anual sem baixá-lo (cabeçalhos do HEAD)."""

    ano: int
    url: str
    ultima_modificacao: str | None
    tamanho_bytes: int | None


def url_zip_anual(ano: int) -> str:
    return f"{URL_DADOS_HISTORICOS}/{ano}.zip"


class InmetClient:
    """Cliente HTTP com headers defensivos para o portal do INMET."""

    def __init__(self, cliente_http: httpx.Client | None = None) -> None:
        self._cliente = cliente_http
        self.headers = {"User-Agent": "InflaTrack/1.0 (Weather Ingestion Pipeline)"}

    @contextmanager
    def _http(self) -> Iterator[httpx.Client]:
        if self._cliente is not None:
            yield self._cliente
            return
        with httpx.Client(follow_redirects=True) as cliente:
            yield cliente

    def _get(self, endpoint: str, timeout: float = 30.0) -> Any:
        url = f"{BASE_URL}/{endpoint.lstrip('/')}"
        with self._http() as cliente:
            resposta = cliente.get(url, headers=self.headers, timeout=timeout)
            resposta.raise_for_status()
            return resposta.json()

    def listar_estacoes(self, tipo: str = "T") -> list[dict[str, Any]]:
        """Busca o catálogo de estações do INMET (T=Todas, A=Automáticas, M=Manuais)."""
        payload = self._get(f"estacoes/{tipo}")
        if not isinstance(payload, list):
            raise InmetError(f"Formato inesperado ao listar estações: {type(payload)}")
        return payload

    def versao_zip_anual(self, ano: int) -> VersaoZip | None:
        """Consulta (HEAD) o pacote anual do BDMEP. ``None`` se o ano ainda não foi publicado."""
        url = url_zip_anual(ano)
        with self._http() as cliente:
            resposta = cliente.head(url, headers=self.headers, timeout=30.0)
        if resposta.status_code == 404:
            return None
        resposta.raise_for_status()
        tamanho = resposta.headers.get("content-length", "")
        return VersaoZip(
            ano=ano,
            url=url,
            ultima_modificacao=resposta.headers.get("last-modified"),
            tamanho_bytes=int(tamanho) if tamanho.isdigit() else None,
        )

    def baixar_zip_anual(self, ano: int, destino: Path) -> Path:
        """Baixa o pacote anual do BDMEP em streaming para ``destino`` e devolve o caminho."""
        url = url_zip_anual(ano)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with (
            self._http() as cliente,
            cliente.stream("GET", url, headers=self.headers, timeout=TIMEOUT_ZIP) as resposta,
        ):
            resposta.raise_for_status()
            with destino.open("wb") as arquivo:
                for bloco in resposta.iter_bytes(chunk_size=1 << 20):
                    arquivo.write(bloco)
        if destino.stat().st_size == 0:
            raise InmetError(f"Pacote {url} veio vazio")
        return destino


def _para_float(valor: Any) -> float | None:
    if valor is None or valor == "":
        return None
    try:
        numero = float(valor)
    except (ValueError, TypeError):
        return None
    if not isfinite(numero) or numero in {-9999.0, 9999.0, 9999.9}:
        return None
    return numero


def _primeiro_valor(*valores: Any) -> Any:
    return next((valor for valor in valores if valor is not None and valor != ""), None)


def transformar_estacoes(payload: list[dict[str, Any]]) -> pd.DataFrame:
    """Transforma a lista de estações da API em DataFrame estruturado."""
    registros: list[dict[str, Any]] = []

    for item in payload:
        if not isinstance(item, dict):
            continue
        estacao_id = item.get("CD_ESTACAO") or item.get("estacao_id")
        nome = item.get("DC_NOME") or item.get("nome")
        estado = item.get("SG_ESTADO") or item.get("estado")
        tipo = item.get("TP_ESTACAO") or item.get("tipo")
        situacao = item.get("CD_SITUACAO") or item.get("situacao")

        if not estacao_id or not nome or not estado:
            continue

        registros.append(
            {
                "estacao_id": str(estacao_id).strip(),
                "nome": str(nome).strip(),
                "estado": str(estado).strip(),
                "tipo": str(tipo).strip() if tipo else None,
                "latitude": _para_float(
                    _primeiro_valor(item.get("VL_LATITUDE"), item.get("latitude"))
                ),
                "longitude": _para_float(
                    _primeiro_valor(item.get("VL_LONGITUDE"), item.get("longitude"))
                ),
                "altitude_m": _para_float(
                    _primeiro_valor(item.get("VL_ALTITUDE"), item.get("altitude_m"))
                ),
                "situacao": str(situacao).strip() if situacao else None,
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

        temp_min = _para_float(
            _primeiro_valor(item.get("TEM_MIN"), item.get("temp_min"), item.get("MIN_TEMP"))
        )
        temp_max = _para_float(
            _primeiro_valor(item.get("TEM_MAX"), item.get("temp_max"), item.get("MAX_TEMP"))
        )
        temp_med = _para_float(
            _primeiro_valor(item.get("TEM_MED"), item.get("temp_media"), item.get("TEMP"))
        )
        if temp_med is None and temp_min is not None and temp_max is not None:
            temp_med = round((temp_min + temp_max) / 2.0, 2)

        chuva = _para_float(
            _primeiro_valor(
                item.get("CHUVA"),
                item.get("precipitacao_total_mm"),
                item.get("PRECIPITACAO_TOTAL"),
                item.get("RAIN"),
            )
        )

        umd_med = _para_float(
            _primeiro_valor(
                item.get("UMD_MED"), item.get("umidade_relativa_media_pct"), item.get("HUMI")
            )
        )
        umd_min = _para_float(
            _primeiro_valor(
                item.get("UMD_MIN"), item.get("umidade_relativa_min_pct"), item.get("MIN_RH")
            )
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
