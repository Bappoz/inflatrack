import requests
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class OlindaClient:
    BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"

    def buscar_dolar(self, data_inicial: str, data_final: str) -> List[Dict[str, Any]]:
        params = {
            "@dataInicial": f"'{data_inicial}'",
            "@dataFinalCotacao": f"'{data_final}'",
            "$format": "json"
        }
        logger.info(f"Buscando Dólar na API Olinda entre {data_inicial} e {data_final}")
        response = requests.get(self.BASE_URL, params=params)
        response.raise_for_status()
        return response.json().get("value", [])
