"""Ingestão das Contas Nacionais Trimestrais (SIDRA 1846) — PIB e setores.

Uso::

    uv run python -m inflatrack.ingest_pib --de 1996 --ate 2026

A carga é ELT, igual à das commodities: grava a resposta crua em
``data/raw/pib_raw/`` (um JSON gzip por ano) e só depois transforma em Parquet
em ``data/parquet/pib/``. A camada crua existe para reprocessar e para provar
de onde veio o número.

O Parquet fica em **subpasta** (``data/parquet/pib/``) de propósito:
``inflatrack.load_commodities`` lê ``data/parquet/*.parquet`` com glob raso e
espera o esquema ``(symbol, data_referencia, preco)``. Um arquivo de PIB solto
ali quebraria a carga das commodities.

Idempotente: reexecutar sobrescreve o bruto e o Parquet do mesmo ano. O IBGE
revisa trimestres antigos a cada divulgação, então reprocessar é o caminho
normal de atualização, não exceção.
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

from inflatrack import pib, sidra

logger = logging.getLogger("inflatrack.ingest_pib")

RAW_DIR_PADRAO = Path("data/raw/pib_raw")
PARQUET_DIR_PADRAO = Path("data/parquet/pib")

COLUNAS = [
    "codigo_setor",
    "setor",
    "grupo",
    "nucleo",
    "data_referencia",
    "ano",
    "trimestre",
    "valor_milhoes_brl",
]


def gravar_bruto(destino: Path, ano: int, payload: list[dict]) -> Path:
    """Congela a resposta da API em gzip, antes de qualquer transformação."""
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{pib.AGREGADO}-{ano}.json.gz"
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        json.dump(payload, arquivo, ensure_ascii=False)
    return caminho


def ler_bruto(caminho: Path) -> list[dict]:
    """Relê o arquivo cru — o Parquet sempre nasce do que foi gravado em raw."""
    with gzip.open(caminho, "rt", encoding="utf-8") as arquivo:
        return json.load(arquivo)


def transformar(payload: list[dict], catalogo: dict[str, tuple[str, str, bool]]) -> pd.DataFrame:
    """Converte o payload compacto do SIDRA no formato do Parquet.

    ``catalogo`` mapeia ``codigo -> (nome, grupo, nucleo)``, vindo dos
    metadados do agregado. Linhas com marcador de ausência (``...``, ``-``,
    ``X``) são descartadas — mas ``-0.67`` é valor negativo de verdade, ver
    :func:`inflatrack.sidra.eh_ausente`.
    """
    linhas = []
    for item in payload:
        valor = item["V"]
        if sidra.eh_ausente(valor):
            continue
        codigo = item["D4C"]
        nome, grupo, nucleo = catalogo.get(codigo, (codigo, pib.GRUPO_AGREGADO, False))
        periodo = item["D3C"]
        referencia = pib.trimestre_para_data(periodo)
        linhas.append(
            {
                "codigo_setor": codigo,
                "setor": nome,
                "grupo": grupo,
                "nucleo": nucleo,
                "data_referencia": referencia,
                "ano": referencia.year,
                "trimestre": (referencia.month + 2) // 3,
                "valor_milhoes_brl": float(valor),
            }
        )

    quadro = pd.DataFrame(linhas, columns=COLUNAS)
    if quadro.empty:
        return quadro
    return quadro.sort_values(["data_referencia", "grupo", "codigo_setor"], ignore_index=True)


def executar(args: argparse.Namespace) -> int:
    raw_dir, parquet_dir = Path(args.raw_dir), Path(args.parquet_dir)
    parquet_dir.mkdir(parents=True, exist_ok=True)
    total = 0

    with httpx.Client() as cliente:
        metadados = sidra.buscar_metadados(cliente, pib.AGREGADO)
        setores = pib.setores(metadados)
        catalogo = {codigo: (nome, grupo, nucleo) for codigo, nome, grupo, nucleo in setores}
        logger.info(
            "catálogo do agregado %d: %d setores (%d no núcleo)",
            pib.AGREGADO,
            len(catalogo),
            sum(1 for _, _, _, nucleo in setores if nucleo),
        )

        for ano in range(args.de, args.ate + 1):
            payload = sidra.buscar_valores(
                cliente,
                pib.AGREGADO,
                pib.periodo_do_ano(ano),
                niveis=pib.NIVEIS,
                classificacao=pib.CLASSIFICACAO,
            )
            if not payload:
                logger.info("%d: sem dados publicados, ignorado", ano)
                continue

            bruto = gravar_bruto(raw_dir, ano, payload)
            quadro = transformar(ler_bruto(bruto), catalogo)
            if quadro.empty:
                logger.warning("%d: %d valores, todos ausentes", ano, len(payload))
                continue

            destino = parquet_dir / f"{pib.AGREGADO}-{ano}.parquet"
            quadro.to_parquet(destino, index=False)
            total += len(quadro)
            logger.info("%d: %d linhas -> %s", ano, len(quadro), destino)

    logger.info("total transformado: %d linhas em %s", total, parquet_dir)
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--de", type=int, default=1996, metavar="AAAA", help="ano inicial")
    parser.add_argument("--ate", type=int, default=2026, metavar="AAAA", help="ano final")
    parser.add_argument("--raw-dir", default=str(RAW_DIR_PADRAO))
    parser.add_argument("--parquet-dir", default=str(PARQUET_DIR_PADRAO))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.de > args.ate:
        parser.error("--de não pode ser maior que --ate")
    try:
        executar(args)
    except (sidra.SidraError, ValueError) as erro:
        logger.error("carga abortada: %s", erro)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
