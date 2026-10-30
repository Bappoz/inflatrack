import logging
import os
import time
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

from inflatrack import bronze

load_dotenv()

logger = logging.getLogger(__name__)

ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")


class AlphaVantageClient:
    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or ALPHAVANTAGE_API_KEY
        if not self.api_key:
            logger.warning("ALPHAVANTAGE_API_KEY is not set. Requests may fail.")
        self.last_request_time = 0.0

    def _rate_limit(self):
        # 5 requests per minute limit in free tier -> 12 seconds between requests
        # Added a small margin (13 seconds) to be safe
        elapsed = time.time() - self.last_request_time
        if elapsed < 13.0 and self.last_request_time > 0:
            sleep_time = 13.0 - elapsed
            logger.info(f"Rate limiting... sleeping for {sleep_time:.2f} seconds")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    @classmethod
    def url_publica(cls, function: str, interval: str) -> str:
        """URL da requisição SEM a chave: é o que vai para ``_requisicao`` na Bronze."""
        return f"{cls.BASE_URL}?{urlencode({'function': function, 'interval': interval})}"

    def buscar_resposta(self, function: str, interval: str = "daily") -> bronze.Resposta:
        """Busca uma commodity e devolve a resposta como veio, sem interpretar o corpo.

        Erro HTTP vira exceção. A cota esgotada chega com status 200 e é tratada por
        quem interpreta o corpo (``ingest_commodities.validar``).
        """
        self._rate_limit()
        params = {"function": function, "interval": interval, "apikey": self.api_key}
        logger.info(f"Buscando commodity: {function} (intervalo: {interval})")
        response = requests.get(self.BASE_URL, params=params, timeout=60)
        response.raise_for_status()
        return bronze.Resposta(
            url=self.url_publica(function, interval),
            status_http=response.status_code,
            tipo_conteudo=response.headers.get("content-type"),
            corpo=response.text,
        )
