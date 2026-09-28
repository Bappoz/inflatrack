"""Ingestão dos dados de estações e clima do INMET.

Baixa o cadastro de estações e medições diárias, salvando em ``data/raw/inmet/``
e gerando os Parquets em ``data/parquet/clima/``. A carga no DuckDB é feita
por ``load_clima.py``.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from inflatrack.inmet import (
    InmetClient,
    InmetError,
    transformar_clima_diario,
    transformar_estacoes,
)

logger = logging.getLogger("inflatrack.ingest_clima")

RAW_DIR_PADRAO = Path("data/raw/inmet")
PARQUET_DIR_PADRAO = Path("data/parquet/clima")


def gravar_bruto(destino_dir: Path, nome_arquivo: str, payload: Any) -> Path:
    """Grava o payload bruto em JSON comprimido com gzip."""
    destino_dir.mkdir(parents=True, exist_ok=True)
    caminho = destino_dir / f"{nome_arquivo}.json.gz"
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        json.dump(payload, arquivo, ensure_ascii=False)
    return caminho


def processar_estacoes(
    cliente: InmetClient,
    raw_dir: Path = RAW_DIR_PADRAO,
    parquet_dir: Path = PARQUET_DIR_PADRAO,
) -> pd.DataFrame:
    """Coleta e materializa o catálogo cadastral de estações do INMET."""
    logger.info("Consultando catálogo de estações ativas do INMET...")
    payload = cliente.listar_estacoes(tipo="T")
    gravar_bruto(raw_dir, "estacoes", payload)
    logger.info("Raw de estações arquivado em %s", raw_dir / "estacoes.json.gz")

    df = transformar_estacoes(payload)
    parquet_dir.mkdir(parents=True, exist_ok=True)
    caminho_parquet = parquet_dir / "estacoes.parquet"
    df.to_parquet(caminho_parquet, index=False)
    logger.info("Salvo catálogo com %d estações em %s", len(df), caminho_parquet)
    return df


def processar_medicoes(
    payload_medicoes: list[dict[str, Any]],
    raw_dir: Path = RAW_DIR_PADRAO,
    parquet_dir: Path = PARQUET_DIR_PADRAO,
    nome_raw: str = "clima_diario",
) -> pd.DataFrame:
    """Processa medições diárias brutas, gerando raw e parquet."""
    gravar_bruto(raw_dir, nome_raw, payload_medicoes)
    df = transformar_clima_diario(payload_medicoes)
    parquet_dir.mkdir(parents=True, exist_ok=True)
    caminho_parquet = parquet_dir / "clima_diario.parquet"
    df.to_parquet(caminho_parquet, index=False)
    logger.info("Salvas %d observações diárias em %s", len(df), caminho_parquet)
    return df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default=str(RAW_DIR_PADRAO))
    parser.add_argument("--parquet-dir", default=str(PARQUET_DIR_PADRAO))
    parser.add_argument(
        "--apenas-estacoes",
        action="store_true",
        help="Sincroniza apenas o cadastro de estações meteorológicas",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cliente = InmetClient()

    try:
        processar_estacoes(cliente, raw_dir=Path(args.raw_dir), parquet_dir=Path(args.parquet_dir))
        return 0
    except InmetError as exc:
        logger.error("Erro na API do INMET: %s", exc)
        return 1
    except Exception as exc:
        logger.exception("Falha inesperada na ingestão do clima: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
