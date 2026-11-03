"""Cliente para a API do Banco Mundial (World Bank API v2).

Permite consultar indicadores econômicos anuais por país (como crescimento percentual
do PIB e PIB nominal em dólares americanos) de forma parametrizada e padronizada.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from inflatrack.common.bronze import Resposta

logger = logging.getLogger(__name__)

BASE_URL = "https://api.worldbank.org/v2"
API_URL_TEMPLATE = "https://api.worldbank.org/v2/country/{pais}/indicator/{indicador}"

INDICADOR_CRESCIMENTO = "NY.GDP.MKTP.KD.ZG"
INDICADOR_PIB_USD = "NY.GDP.MKTP.CD"

INDICADORES = {
    "crescimento": INDICADOR_CRESCIMENTO,
    "pib_usd": INDICADOR_PIB_USD,
}

PAISES = {
    "CHN": "China",
    "USA": "Estados Unidos",
    "RUS": "Rússia",
}


class WorldBankError(ValueError):
    """Resposta inválida, com erro HTTP ou incompleta da API do Banco Mundial."""


class WorldBankClient:
    """Cliente HTTP para a API v2 do Banco Mundial."""

    def __init__(self, cliente: httpx.Client | None = None, timeout: float = 30.0) -> None:
        self._cliente_proprio = cliente is None
        self.cliente = cliente or httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "InflaTrack/0.1", "Accept": "application/json"},
        )
        self.timeout = timeout

    def __enter__(self) -> WorldBankClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._cliente_proprio:
            self.cliente.close()

    @staticmethod
    def url_publica(pais: str, indicador: str, per_page: int = 1000) -> str:
        """Retorna a URL completa da requisição da API."""
        query = urlencode({"format": "json", "per_page": per_page})
        return f"{API_URL_TEMPLATE.format(pais=pais.upper(), indicador=indicador)}?{query}"

    def buscar_resposta(self, pais: str, indicador: str, per_page: int = 1000) -> Resposta:
        """Executa a requisição HTTP e retorna Resposta bruta (para auditoria e camada Bronze)."""
        url = self.url_publica(pais, indicador, per_page=per_page)
        logger.info("Buscando indicador %s para o país %s no Banco Mundial", indicador, pais)
        try:
            resp = self.cliente.get(
                API_URL_TEMPLATE.format(pais=pais.upper(), indicador=indicador),
                params={"format": "json", "per_page": per_page},
            )
            resp.raise_for_status()
        except httpx.HTTPError as err:
            raise WorldBankError(
                f"Erro na requisição ao Banco Mundial ({pais}/{indicador}): {err}"
            ) from err

        return Resposta(
            url=url,
            status_http=resp.status_code,
            tipo_conteudo=resp.headers.get("content-type"),
            corpo=resp.text,
        )

    def buscar_payload(self, pais: str, indicador: str, per_page: int = 1000) -> list:
        """Executa a requisição e valida a estrutura JSON retornada pela API."""
        resposta = self.buscar_resposta(pais, indicador, per_page=per_page)
        try:
            payload = httpx.Response(status_code=200, text=resposta.corpo).json()
        except Exception as err:
            raise WorldBankError(f"Falha ao decodificar JSON do Banco Mundial: {err}") from err

        if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
            raise WorldBankError(
                f"Formato inesperado retornado pelo Banco Mundial para {pais}/{indicador}"
            )
        return payload
