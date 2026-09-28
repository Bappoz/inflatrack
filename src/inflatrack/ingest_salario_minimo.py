"""Ingestão mensal do Salário Mínimo Nominal e Necessário do DIEESE.

Grava o HTML bruto compactado em ``data/raw/dieese/`` e materializa um Parquet
em ``data/parquet/dieese/``. A carga no DuckDB é feita por ``load_salario_minimo``.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import sys
from pathlib import Path

import pandas as pd

from inflatrack.dieese import DieeseError, baixar_html, extrair_tabela

logger = logging.getLogger("inflatrack.ingest_salario_minimo")

RAW_DIR_PADRAO = Path("data/raw/dieese")
PARQUET_DIR_PADRAO = Path("data/parquet/dieese")


def gravar_bruto(destino_dir: Path, html_conteudo: str) -> Path:
    """Grava o conteúdo HTML integral em gzip na camada raw."""
    destino_dir.mkdir(parents=True, exist_ok=True)
    caminho = destino_dir / "salario_minimo.html.gz"
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        arquivo.write(html_conteudo)
    return caminho


def processar(
    raw_dir: Path = RAW_DIR_PADRAO,
    parquet_dir: Path = PARQUET_DIR_PADRAO,
    html_conteudo: str | None = None,
) -> pd.DataFrame:
    """Executa a extração do HTML, gravação raw e conversão para Parquet."""
    if html_conteudo is None:
        logger.info("Baixando página de salário mínimo do DIEESE...")
        html_conteudo = baixar_html()

    caminho_raw = gravar_bruto(raw_dir, html_conteudo)
    logger.info("HTML bruto salvo em %s (%d bytes)", caminho_raw, len(html_conteudo))

    logger.info("Extraindo tabela de séries históricas...")
    df = extrair_tabela(html_conteudo)
    logger.info("Extraídos %d registros mensais de salário mínimo", len(df))

    parquet_dir.mkdir(parents=True, exist_ok=True)
    caminho_parquet = parquet_dir / "salario_minimo.parquet"
    df.to_parquet(caminho_parquet, index=False)
    logger.info("Parquet salvo com sucesso em %s", caminho_parquet)

    return df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default=str(RAW_DIR_PADRAO), help="Diretório da camada raw")
    parser.add_argument(
        "--parquet-dir", default=str(PARQUET_DIR_PADRAO), help="Diretório da camada Parquet"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        processar(raw_dir=Path(args.raw_dir), parquet_dir=Path(args.parquet_dir))
        return 0
    except DieeseError as exc:
        logger.error("Erro no processamento do DIEESE: %s", exc)
        return 1
    except Exception as exc:
        logger.exception("Falha inesperada na ingestão do DIEESE: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
