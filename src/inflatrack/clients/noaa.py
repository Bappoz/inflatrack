"""Cliente HTTP do NOAA/CPC para o RONI (Relative Oceanic Niño Index).

O RONI é a anomalia da temperatura da superfície do mar na região Niño 3.4, em média móvel de
3 meses, descontada da média tropical. O NOAA o adotou em 2026 no lugar do ONI, e o Banco Central
o usa para medir El Niño e La Niña (Relatório de Política Monetária, set/2026). Público, sem
chave. Este módulo só fala com a internet; ler e gravar é de ``inflatrack.bronze.enso``.
"""

from __future__ import annotations

import httpx

URL_RONI = "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt"


class NoaaError(ValueError):
    """Resposta inválida do NOAA."""


class NoaaClient:
    def __init__(self, cliente_http: httpx.Client | None = None) -> None:
        self._cliente = cliente_http
        self.headers = {"User-Agent": "InflaTrack/1.0 (Climate Index Ingestion)"}

    def buscar_roni(self) -> tuple[str, str]:
        """Baixa a série inteira do RONI; devolve (URL, texto)."""
        if self._cliente is not None:
            resposta = self._cliente.get(URL_RONI, headers=self.headers)
        else:
            with httpx.Client(timeout=60.0, follow_redirects=True) as cliente:
                resposta = cliente.get(URL_RONI, headers=self.headers)
        if resposta.status_code >= 400:
            raise NoaaError(f"NOAA respondeu {resposta.status_code} para {URL_RONI}")
        return URL_RONI, resposta.text
