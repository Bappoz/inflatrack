"""Carga do IPCA/INPC do SIDRA para o banco transacional.

Uso::

    uv run python -m inflatrack.ingest --agregado 7060 --de 2026-01 --ate 2026-07

A carga é ELT: grava a resposta crua em ``data/raw/`` (gzip, ~18x menor) e só
depois transforma dentro do banco. A camada crua existe para reprocessar e para
provar de onde veio o número — não para ser consultada.

Idempotente: reexecutar com o mesmo dado não insere nada (índice único inclui o
valor). Se o IBGE revisar um mês já carregado, a revisão entra como linha nova.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

import httpx
import psycopg

from inflatrack import sidra

logger = logging.getLogger("inflatrack.ingest")

COLUNAS_OBSERVACAO = (
    "id_fonte",
    "codigo_classificacao",
    "codigo_localidade",
    "codigo_variavel",
    "mes_referencia",
    "valor",
)


def dsn_do_ambiente() -> str:
    """Monta o DSN a partir do .env / variáveis de ambiente."""
    usuario = os.environ.get("POSTGRES_USER", "inflatrack")
    senha = os.environ.get("POSTGRES_PASSWORD", "inflatrack")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    porta = os.environ.get("POSTGRES_PORT", "5432")
    banco = os.environ.get("POSTGRES_DB", "inflatrack")
    return f"postgresql://{usuario}:{senha}@{host}:{porta}/{banco}"


def mes_para_data(periodo: str) -> date:
    """``"202607"`` -> ``date(2026, 7, 1)``."""
    return date(int(periodo[:4]), int(periodo[4:]), 1)


def gravar_bruto(destino: Path, agregado: int, periodo: str, payload: list[dict]) -> Path:
    """Congela a resposta da API em gzip, para auditoria e reprocessamento."""
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{agregado}-{periodo}.json.gz"
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        json.dump(payload, arquivo, ensure_ascii=False)
    return caminho


def sincronizar_cesta(
    conexao: psycopg.Connection, agregado: int, metadados: dict
) -> dict[str, str]:
    """Insere a classificação e a versão vigente daquele agregado.

    A versão existe porque o mesmo código muda de nome entre agregados — 43
    subitens foram renomeados entre 2006 e 2026. Ver docs/adr/0001.

    Devolve o mapa ``id_sidra -> codigo`` desse agregado: os valores da API
    identificam a categoria pelo ``id`` interno (``D4C``), não pelo código
    natural gravado em `classificacao`.
    """
    categorias = sidra.categorias(metadados)
    periodo = metadados["periodicidade"]
    vigencia_inicio = mes_para_data(str(periodo["inicio"]))

    with conexao.cursor() as cursor:
        cursor.executemany(
            "insert into classificacao (codigo, nivel) values (%s, %s)"
            " on conflict (codigo) do nothing",
            [(codigo, sidra.nivel_do_codigo(codigo)) for _, codigo, _, _ in categorias],
        )
        cursor.executemany(
            "insert into classificacao_versao"
            " (codigo, id_fonte, nome, codigo_pai, vigencia_inicio)"
            " values (%s, %s, %s, %s, %s)"
            " on conflict (codigo, id_fonte) do update set nome = excluded.nome",
            [(codigo, agregado, nome, pai, vigencia_inicio) for _, codigo, nome, pai in categorias],
        )
    return {id_sidra: codigo for id_sidra, codigo, _, _ in categorias}


def carregar_periodo(
    conexao: psycopg.Connection,
    agregado: int,
    periodo: str,
    payload: list[dict],
    mapa_classificacao: dict[str, str] | None,
) -> int:
    """Copia um mês para uma tabela temporária e funde na tabela de fato.

    ``mapa_classificacao`` traduz o ``D4C`` (id interno do SIDRA) para o
    código natural gravado em `classificacao` — ver :func:`sincronizar_cesta`.
    Agregados sem dimensão de classificação (1737) não têm ``D4C`` no payload
    e caem sempre no índice geral.
    """
    mes = mes_para_data(periodo)
    linhas = [
        (
            agregado,
            mapa_classificacao[linha["D4C"]] if mapa_classificacao else sidra.CODIGO_INDICE_GERAL,
            int(linha["D1C"]),
            int(linha["D2C"]),
            mes,
            linha["V"],
        )
        for linha in payload
        if not sidra.eh_ausente(linha["V"])
    ]
    if not linhas:
        return 0

    with conexao.cursor() as cursor:
        cursor.execute(
            "create temp table carga (like observacao including defaults including identity)"
            " on commit drop"
        )
        colunas = ", ".join(COLUNAS_OBSERVACAO)
        with cursor.copy(f"copy carga ({colunas}) from stdin") as copia:
            for linha in linhas:
                copia.write_row(linha)
        cursor.execute(
            f"insert into observacao ({colunas}) select {colunas} from carga on conflict do nothing"
        )
        return cursor.rowcount


def executar(args: argparse.Namespace) -> int:
    inicio, fim = mes_para_data(args.de.replace("-", "")), mes_para_data(args.ate.replace("-", ""))
    destino_bruto = Path(args.raw_dir)
    total = 0

    with httpx.Client() as cliente, psycopg.connect(args.dsn) as conexao:
        metadados = sidra.buscar_metadados(cliente, args.agregado)
        mapa_classificacao: dict[str, str] | None = None
        if args.agregado != 1737:
            mapa_classificacao = sincronizar_cesta(conexao, args.agregado, metadados)
            conexao.commit()
            logger.info(
                "cesta sincronizada: %d categorias do agregado %d",
                len(mapa_classificacao),
                args.agregado,
            )

        for periodo in sidra.meses(inicio, fim):
            payload = sidra.buscar_valores(
                cliente,
                args.agregado,
                periodo,
                niveis="n1/all" if args.agregado == 1737 else "n1/all/n6/all/n7/all",
                classificacao=None if args.agregado == 1737 else "315",
            )
            gravar_bruto(destino_bruto, args.agregado, periodo, payload)
            inseridas = carregar_periodo(
                conexao, args.agregado, periodo, payload, mapa_classificacao
            )
            conexao.commit()
            total += inseridas
            logger.info("%s/%s: %d linhas novas", args.agregado, periodo, inseridas)

    logger.info("total inserido: %d linhas", total)
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agregado", type=int, required=True, help="2938, 1419, 7060, 7063 ou 1737"
    )
    parser.add_argument("--de", required=True, metavar="AAAA-MM")
    parser.add_argument("--ate", required=True, metavar="AAAA-MM")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--dsn", default=None)
    args = parser.parse_args(argv)
    args.dsn = args.dsn or dsn_do_ambiente()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        executar(args)
    except (sidra.SidraError, psycopg.Error) as erro:
        logger.error("carga abortada: %s", erro)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
