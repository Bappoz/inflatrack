"""Ingestão dos dados de Cesta Básica do PROCON.

Grava o CSV bruto compactado em ``data/raw/procon/`` e materializa a tabela Delta
em ``data/parquet/procon/``. A carga no DuckDB é feita por ``load_procon.py``.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import sys
from pathlib import Path

from inflatrack.bronze import bronze_procon

logger = logging.getLogger("inflatrack.ingest_procon")

RAW_DIR_PADRAO = Path("data/raw/procon")
DELTA_DIR_PADRAO = Path("data/parquet/procon")


def gravar_bruto(
    destino_dir: Path, csv_conteudo: str, nome_arquivo: str = "cesta_basica.csv.gz"
) -> Path:
    """Grava o conteúdo CSV bruto em gzip na camada raw."""
    destino_dir.mkdir(parents=True, exist_ok=True)
    caminho = destino_dir / nome_arquivo
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        arquivo.write(csv_conteudo)
    return caminho


def processar(
    caminho_csv: Path | None = None,
    raw_dir: Path = RAW_DIR_PADRAO,
    delta_dir: Path = DELTA_DIR_PADRAO,
    csv_conteudo: str | None = None,
) -> bronze_procon.Gravacao:
    """Executa a gravação raw e a promoção para Delta Bronze."""
    if csv_conteudo is None:
        if caminho_csv is not None and caminho_csv.is_file():
            csv_conteudo = caminho_csv.read_text(encoding="utf-8")
        else:
            # Se não fornecido arquivo, tenta carregar fixture padrão se existir
            fixture_padrao = Path("tests/fixtures/procon/cesta_basica.csv")
            if fixture_padrao.is_file():
                csv_conteudo = fixture_padrao.read_text(encoding="utf-8")
                caminho_csv = fixture_padrao
            else:
                raise FileNotFoundError(
                    "Nenhum conteúdo ou arquivo CSV fornecido para ingestão do PROCON."
                )

    origem = str(caminho_csv) if caminho_csv else "payload_memoria"
    caminho_raw = gravar_bruto(raw_dir, csv_conteudo)
    logger.info("CSV bruto salvo em %s (%d bytes)", caminho_raw, len(csv_conteudo))

    grav = bronze_procon.promover_cesta_basica(
        csv_conteudo,
        requisicao=origem,
        destino=delta_dir,
    )
    logger.info(
        "Bronze Delta PROCON: resposta %s, %d de %d linhas novas em %s",
        "nova" if grav.respostas_novas else "já guardada",
        grav.linhas_novas,
        grav.linhas_lidas,
        delta_dir,
    )
    return grav


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestão da Cesta Básica do PROCON")
    parser.add_argument(
        "--arquivo", type=Path, default=None, help="Caminho do arquivo CSV de entrada"
    )
    parser.add_argument(
        "--raw-dir", type=Path, default=RAW_DIR_PADRAO, help="Diretório da camada raw"
    )
    parser.add_argument(
        "--delta-dir", type=Path, default=DELTA_DIR_PADRAO, help="Diretório Delta Bronze"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        resultado = processar(
            caminho_csv=args.arquivo, raw_dir=args.raw_dir, delta_dir=args.delta_dir
        )
        print(f"Sucesso: {resultado.linhas_novas} registros novos promovidos para {args.delta_dir}")
    except Exception as err:
        logger.error("Falha na ingestão: %s", err)
        sys.exit(1)


if __name__ == "__main__":
    main()
