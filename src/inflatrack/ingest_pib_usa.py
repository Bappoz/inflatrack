"""Ingestão anual do PIB dos EUA pela API pública do Banco Mundial.

Grava a resposta original em ``data/raw/pib_usa/``, materializa um Parquet
em ``data/parquet/pib_usa/`` e atualiza as tabelas Delta Lake da Bronze.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from pathlib import Path

import httpx
import pandas as pd

logger = logging.getLogger("inflatrack.ingest_pib_usa")

API_URL = "https://api.worldbank.org/v2/country/USA/indicator/{indicador}"
INDICADOR_CRESCIMENTO = "NY.GDP.MKTP.KD.ZG"
INDICADOR_PIB_USD = "NY.GDP.MKTP.CD"
RAW_DIR_PADRAO = Path("data/raw/pib_usa")
PARQUET_DIR_PADRAO = Path("data/parquet/pib_usa")
COLUNAS = ["ano", "crescimento_pib_pct", "pib_usd"]


class WorldBankError(ValueError):
    """Resposta inválida ou incompleta da API do Banco Mundial."""


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


def transformar(payload_crescimento: list, payload_pib_usd: list) -> pd.DataFrame:
    valores: dict[int, dict[str, float | int | None]] = {}

    for payload, coluna in (
        (payload_crescimento, "crescimento_pib_pct"),
        (payload_pib_usd, "pib_usd"),
    ):
        if len(payload) < 2 or not isinstance(payload[1], list):
            raise WorldBankError(f"payload inválido para {coluna}")
        for item in payload[1]:
            if not isinstance(item, dict):
                raise WorldBankError(f"observação inválida para {coluna}")
            ano_texto = item.get("date")
            if not isinstance(ano_texto, str) or not ano_texto.isdigit():
                raise WorldBankError(f"ano inválido para {coluna}: {ano_texto!r}")
            ano = int(ano_texto)
            valor = item.get("value")
            valores.setdefault(ano, {"ano": ano})[coluna] = (
                float(valor) if valor is not None else None
            )

    quadro = pd.DataFrame(valores.values(), columns=COLUNAS)
    if quadro.empty:
        raise WorldBankError("a API não retornou observações")
    return quadro.sort_values("ano", ignore_index=True)


def executar(args: argparse.Namespace) -> int:
    raw_dir = Path(args.raw_dir)
    parquet_dir = Path(args.parquet_dir)

    with httpx.Client(follow_redirects=True) as cliente:
        logger.info("coletando crescimento anual do PIB dos EUA")
        payload_crescimento = buscar_payload(cliente, INDICADOR_CRESCIMENTO)
        gravar_bruto(raw_dir, INDICADOR_CRESCIMENTO, payload_crescimento)

        logger.info("coletando PIB nominal anual dos EUA em USD")
        payload_pib_usd = buscar_payload(cliente, INDICADOR_PIB_USD)
        gravar_bruto(raw_dir, INDICADOR_PIB_USD, payload_pib_usd)

    quadro = transformar(payload_crescimento, payload_pib_usd)
    parquet_dir.mkdir(parents=True, exist_ok=True)
    destino = parquet_dir / "pib_usa.parquet"
    quadro.to_parquet(destino, index=False)
    logger.info("%d anos transformados em %s", len(quadro), destino)

    # Bronze em Delta (E2)
    try:
        from inflatrack import bronze_pib_usa

        req_crescimento = (
            API_URL.format(indicador=INDICADOR_CRESCIMENTO) + "?format=json&per_page=1000"
        )
        bronze_pib_usa.gravar(
            destino=parquet_dir,
            indicador=INDICADOR_CRESCIMENTO,
            requisicao=req_crescimento,
            corpo=json.dumps(payload_crescimento),
        )
        req_pib_usd = API_URL.format(indicador=INDICADOR_PIB_USD) + "?format=json&per_page=1000"
        bronze_pib_usa.gravar(
            destino=parquet_dir,
            indicador=INDICADOR_PIB_USD,
            requisicao=req_pib_usd,
            corpo=json.dumps(payload_pib_usd),
        )
        logger.info("tabelas Delta da Bronze dos EUA atualizadas em %s", parquet_dir)
    except Exception as erro:  # noqa: BLE001
        logger.warning("não foi possível atualizar a Bronze dos EUA em Delta: %s", erro)

    return len(quadro)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default=str(RAW_DIR_PADRAO))
    parser.add_argument("--parquet-dir", default=str(PARQUET_DIR_PADRAO))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        executar(args)
    except (httpx.HTTPError, json.JSONDecodeError, WorldBankError) as erro:
        logger.error("carga abortada: %s", erro)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
