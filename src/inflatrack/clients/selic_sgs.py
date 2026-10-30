"""Cliente do Sistema Gerenciador de Séries Temporais do Banco Central."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


class SGSError(ValueError):
    """Resposta inesperada da API SGS."""


class SGSClient:
    BASE_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "InflaTrack/0.1", "Accept": "application/json"})

    def buscar_serie(
        self,
        codigo_serie: int,
        data_inicial: str | None = None,
        data_final: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {"formato": "json"}
        if data_inicial:
            params["dataInicial"] = data_inicial
        if data_final:
            params["dataFinal"] = data_final

        logger.info("buscando série %d no BCB/SGS", codigo_serie)
        for tentativa in range(2):
            try:
                resposta = self.session.get(
                    self.BASE_URL.format(codigo_serie), params=params, timeout=30.0
                )
                resposta.raise_for_status()
                payload = resposta.json()
                break
            except (requests.RequestException, json.JSONDecodeError):
                if tentativa == 1:
                    raise
                logger.warning("falha transitória na API SGS; repetindo a requisição")
                time.sleep(1)
        if not isinstance(payload, list):
            raise SGSError(f"formato inesperado da série {codigo_serie}")
        return payload
