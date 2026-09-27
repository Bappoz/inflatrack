"""Cliente da API Olinda/PTAX do Banco Central."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


class OlindaError(ValueError):
    """Resposta inesperada da API Olinda."""


class OlindaClient:
    BASE_URL = (
        "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
        "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
    )

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "InflaTrack/0.1")

    def buscar_dolar(self, data_inicial: str, data_final: str) -> list[dict[str, Any]]:
        params = {
            "@dataInicial": f"'{data_inicial}'",
            "@dataFinalCotacao": f"'{data_final}'",
            "$format": "json",
        }
        logger.info("buscando dólar na API Olinda entre %s e %s", data_inicial, data_final)
        for tentativa in range(2):
            try:
                resposta = self.session.get(self.BASE_URL, params=params, timeout=30.0)
                resposta.raise_for_status()
                payload = resposta.json()
                break
            except (requests.RequestException, json.JSONDecodeError):
                if tentativa == 1:
                    raise
                logger.warning("falha transitória na API Olinda; repetindo a requisição")
                time.sleep(1)
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            raise OlindaError("formato inesperado da API Olinda")
        return payload["value"]
