"""Carga do PIB da China a partir da API pública do Banco Mundial (World Bank).

Uso::

    uv run python -m inflatrack.ingest_pib_china

A carga é ELT: grava a resposta crua em ``data/raw/pib_china/`` e depois
transforma e carrega no banco relacional PostgreSQL (tabela ``pib_china``).

Idempotente: reexecutar atualiza ou ignora registros do mesmo ano.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
from pathlib import Path

import httpx
import psycopg

logger = logging.getLogger("inflatrack.ingest_pib_china")

URL_CRESCIMENTO = "https://api.worldbank.org/v2/country/CHN/indicator/NY.GDP.MKTP.KD.ZG?format=json&per_page=100"
URL_VALOR_USD = "https://api.worldbank.org/v2/country/CHN/indicator/NY.GDP.MKTP.CD?format=json&per_page=100"


def dsn_do_ambiente() -> str:
    """Monta o DSN a partir do .env / variáveis de ambiente."""
    usuario = os.environ.get("POSTGRES_USER", "inflatrack")
    senha = os.environ.get("POSTGRES_PASSWORD", "inflatrack")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    porta = os.environ.get("POSTGRES_PORT", "5432")
    banco = os.environ.get("POSTGRES_DB", "inflatrack")
    return f"postgresql://{usuario}:{senha}@{host}:{porta}/{banco}"


def gravar_bruto(destino: Path, nome_serie: str, payload: list) -> Path:
    """Congela a resposta crua da API em gzip para auditoria."""
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{nome_serie}.json.gz"
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        json.dump(payload, arquivo, ensure_ascii=False)
    return caminho


def buscar_dados_banco_mundial(cliente: httpx.Client, url: str) -> list[dict]:
    """Consulta a API do Banco Mundial e retorna a lista de pontos de dados."""
    resposta = cliente.get(url, timeout=30.0)
    resposta.raise_for_status()
    dados = resposta.json()
    if isinstance(dados, list) and len(dados) >= 2 and isinstance(dados[1], list):
        return dados[1]
    return []


def processar_e_carregar(
    conexao: psycopg.Connection,
    dados_crescimento: list[dict],
    dados_valor: list[dict],
) -> int:
    """Processa e realiza UPSERT na tabela pib_china."""
    valores_por_ano: dict[int, dict[str, float | None]] = {}

    for item in dados_crescimento:
        ano_str = item.get("date")
        val = item.get("value")
        if ano_str and ano_str.isdigit():
            ano = int(ano_str)
            valores_por_ano.setdefault(ano, {})["crescimento"] = float(val) if val is not None else None

    for item in dados_valor:
        ano_str = item.get("date")
        val = item.get("value")
        if ano_str and ano_str.isdigit():
            ano = int(ano_str)
            valores_por_ano.setdefault(ano, {})["valor_usd"] = float(val) if val is not None else None

    inseridos = 0
    with conexao.cursor() as cursor:
        for ano, info in sorted(valores_por_ano.items()):
            crescimento = info.get("crescimento")
            valor_usd = info.get("valor_usd")

            cursor.execute(
                """
                insert into pib_china (ano, crescimento_pib_pct, pib_usd)
                values (%s, %s, %s)
                on conflict (ano) do update set
                    crescimento_pib_pct = excluded.crescimento_pib_pct,
                    pib_usd = excluded.pib_usd,
                    criado_em = clock_timestamp()
                """,
                (ano, crescimento, valor_usd),
            )
            inseridos += cursor.rowcount

    return inseridos


def executar(args: argparse.Namespace) -> int:
    destino_bruto = Path(args.raw_dir)

    with httpx.Client(follow_redirects=True) as cliente:
        logger.info("Coletando taxa de crescimento do PIB da China (World Bank)...")
        raw_crescimento = buscar_dados_banco_mundial(cliente, URL_CRESCIMENTO)
        gravar_bruto(destino_bruto, "pib_china_crescimento", raw_crescimento)

        logger.info("Coletando valor nominal do PIB da China em USD (World Bank)...")
        raw_valor = buscar_dados_banco_mundial(cliente, URL_VALOR_USD)
        gravar_bruto(destino_bruto, "pib_china_valor_usd", raw_valor)

    with psycopg.connect(args.dsn) as conexao:
        total = processar_e_carregar(conexao, raw_crescimento, raw_valor)
        conexao.commit()

    logger.info("Carga concluída com sucesso: %d anos processados/atualizados.", total)
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default="data/raw/pib_china")
    parser.add_argument("--dsn", default=None)
    args = parser.parse_args(argv)
    args.dsn = args.dsn or dsn_do_ambiente()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        executar(args)
    except (httpx.HTTPError, psycopg.Error) as erro:
        logger.error("Carga do PIB da China abortada: %s", erro)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
