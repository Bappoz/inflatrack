"""Ingestão anual do PIB dos EUA pela API pública do Banco Mundial.

Módulo de compatibilidade delegando para ``inflatrack.bronze.pib_internacional``.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from pathlib import Path

import httpx

from inflatrack.bronze import pib_internacional
from inflatrack.bronze.pib_internacional import (
    INDICADOR_CRESCIMENTO,
    INDICADOR_PIB_USD,
    WorldBankError,
)

logger = logging.getLogger("inflatrack.ingest_pib_usa")

PAIS = "USA"
API_URL = "https://api.worldbank.org/v2/country/USA/indicator/{indicador}"
RAW_DIR_PADRAO = Path("data/raw/pib_usa")
PARQUET_DIR_PADRAO = Path("data/parquet/pib_usa")
COLUNAS = ["ano", "crescimento_pib_pct", "pib_usd"]


def buscar_payload(cliente: httpx.Client, indicador: str) -> list:
    resposta = cliente.get(
        API_URL.format(indicador=indicador),
        params={"format": "json", "per_page": 1000},
        timeout=30.0,
    )
    resposta.raise_for_status()
    payload = resposta.json()
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise WorldBankError(f"formato inesperado para o indicador {indicador}")
    return payload


def gravar_bruto(destino: Path, indicador: str, payload: list) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{indicador}.json.gz"
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        json.dump(payload, arquivo, ensure_ascii=False)
    return caminho


def transformar(payload_crescimento: list, payload_pib_usd: list):
    return pib_internacional.transformar_largo(payload_crescimento, payload_pib_usd)


def executar(args: argparse.Namespace) -> int:
    return pib_internacional.executar_ingestao_larga(
        pais=PAIS,
        raw_dir=Path(args.raw_dir),
        parquet_dir=Path(args.parquet_dir),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default=str(RAW_DIR_PADRAO))
    parser.add_argument("--parquet-dir", default=str(PARQUET_DIR_PADRAO))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        executar(args)
    except Exception as exc:
        logger.error("falha na ingestão do PIB dos EUA: %s", exc)
        return 1
    return 0


__all__ = [
    "API_URL",
    "COLUNAS",
    "INDICADOR_CRESCIMENTO",
    "INDICADOR_PIB_USD",
    "PAIS",
    "PARQUET_DIR_PADRAO",
    "RAW_DIR_PADRAO",
    "WorldBankError",
    "buscar_payload",
    "executar",
    "gravar_bruto",
    "main",
    "transformar",
]

if __name__ == "__main__":
    sys.exit(main())
