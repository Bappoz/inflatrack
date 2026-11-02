"""Bronze do PIB da Rússia (Banco Mundial) em Delta Lake.

Módulo de compatibilidade delegando para ``inflatrack.bronze.pib_internacional``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from inflatrack.bronze import pib_internacional
from inflatrack.bronze.pib_internacional import (
    CHAVE_INDICADOR,
    ESQUEMA_INDICADOR,
    ESQUEMA_RESPOSTA,
    INDICADOR_CRESCIMENTO,
    INDICADOR_PIB_USD,
    INDICADORES,
    ChecagemError,
    Gravacao,
    WorldBankError,
    hash_do_corpo,
    transformar,
)

logger = logging.getLogger("inflatrack.bronze_pib_russia")

FONTE = "pib_russia"
PAIS = "RUS"
DIRETORIO_PADRAO = Path("data/parquet/pib_russia")
RAW_DIR_PADRAO = Path("data/raw/pib_russia")
API_URL = "https://api.worldbank.org/v2/country/RUS/indicator/{indicador}"


def checar(linhas: list[dict], indicador: str | None = None) -> None:
    pib_internacional.checar(linhas, pais=PAIS, indicador=indicador)


def gravar_resposta(
    destino: Path,
    *,
    requisicao: str,
    corpo: str,
    ingerido_em: datetime,
    status_http: int | None,
    tipo_conteudo: str | None,
) -> tuple[str, bool]:
    return pib_internacional.gravar_resposta(
        destino,
        fonte=FONTE,
        requisicao=requisicao,
        corpo=corpo,
        ingerido_em=ingerido_em,
        status_http=status_http,
        tipo_conteudo=tipo_conteudo,
    )


def acrescentar_indicadores(destino: Path, linhas: list[dict]) -> int:
    return pib_internacional.acrescentar_indicadores(destino, linhas)


def gravar(
    destino: Path,
    indicador: str,
    requisicao: str,
    corpo: str,
    status_http: int | None = 200,
    tipo_conteudo: str | None = "application/json",
    ingerido_em: datetime | None = None,
) -> Gravacao:
    return pib_internacional.gravar(
        destino=destino,
        indicador=indicador,
        requisicao=requisicao,
        corpo=corpo,
        pais=PAIS,
        status_http=status_http,
        tipo_conteudo=tipo_conteudo,
        ingerido_em=ingerido_em,
    )


def coletar_e_gravar(destino: Path = DIRETORIO_PADRAO) -> list[Gravacao]:
    return pib_internacional.coletar_pais(PAIS, destino=destino)


def importar_raw(raw_dir: Path = RAW_DIR_PADRAO, destino: Path = DIRETORIO_PADRAO) -> int:
    return pib_internacional.importar_raw_pais(PAIS, raw_dir=raw_dir, destino=destino)


def checar_tabelas(destino: Path = DIRETORIO_PADRAO) -> None:
    pib_internacional.checar_tabelas_pais(PAIS, destino=destino)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="comando")

    p_coletar = subparsers.add_parser("coletar", help="Coleta da API e grava nas tabelas Delta")
    p_coletar.add_argument("--destino", default=str(DIRETORIO_PADRAO))

    p_importar = subparsers.add_parser("importar", help="Importa raw existente para Delta")
    p_importar.add_argument("--raw-dir", default=str(RAW_DIR_PADRAO))
    p_importar.add_argument("--destino", default=str(DIRETORIO_PADRAO))

    p_checar = subparsers.add_parser("checar", help="Verifica integridade das tabelas Delta")
    p_checar.add_argument("--destino", default=str(DIRETORIO_PADRAO))

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.comando == "coletar" or args.comando is None:
        coletar_e_gravar(Path(getattr(args, "destino", DIRETORIO_PADRAO)))
    elif args.comando == "importar":
        importar_raw(Path(args.raw_dir), Path(args.destino))
    elif args.comando == "checar":
        checar_tabelas(Path(args.destino))

    return 0


__all__ = [
    "API_URL",
    "CHAVE_INDICADOR",
    "DIRETORIO_PADRAO",
    "ESQUEMA_INDICADOR",
    "ESQUEMA_RESPOSTA",
    "FONTE",
    "INDICADOR_CRESCIMENTO",
    "INDICADOR_PIB_USD",
    "INDICADORES",
    "PAIS",
    "RAW_DIR_PADRAO",
    "ChecagemError",
    "Gravacao",
    "WorldBankError",
    "acrescentar_indicadores",
    "checar",
    "checar_tabelas",
    "coletar_e_gravar",
    "gravar",
    "gravar_resposta",
    "hash_do_corpo",
    "importar_raw",
    "main",
    "transformar",
]

if __name__ == "__main__":
    import sys

    sys.exit(main())
