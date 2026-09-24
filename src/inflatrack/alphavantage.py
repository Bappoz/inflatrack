import os
import time
import requests
import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")

class AlphaVantageClient:
    BASE_URL = "https://www.alphavantage.co/query"
    
    def __init__(self, api_key: Optional[str] = None):
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

    def buscar_commodity(self, function: str, interval: str = "daily") -> Dict[str, Any]:
        """
        Busca dados de uma commodity específica na Alpha Vantage.
        """
        self._rate_limit()
        
        params = {
            "function": function,
            "interval": interval,
            "apikey": self.api_key
        }
        
        logger.info(f"Buscando commodity: {function} (intervalo: {interval})")
        response = requests.get(self.BASE_URL, params=params)
        response.raise_for_status()
        
        data = response.json()
        
        if "Information" in data and "rate limit" in data["Information"].lower():
            raise Exception(f"Rate limit exceeded: {data['Information']}")
            
        return data
