import requests
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class SGSClient:
    BASE_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{}/dados"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 InflaTrack/1.0",
            "Accept": "application/json"
        })

    def buscar_serie(self, codigo_serie: int, data_inicial: str = None, data_final: str = None) -> List[Dict[str, Any]]:
        url = self.BASE_URL.format(codigo_serie)
        params = {"formato": "json"}
        if data_inicial:
            params["dataInicial"] = data_inicial
        if data_final:
            params["dataFinal"] = data_final
            
        logger.info(f"Buscando série {codigo_serie} no BCB (SGS)")
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()
