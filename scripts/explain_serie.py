"""Mede a consulta de scripts/sql/explain_serie.sql no Postgres, sem e com o índice.

O "sem índice" apaga o índice dentro de uma transação desfeita no fim: o banco termina como
começou. Cada caso roda várias vezes, porque a primeira execução lê do disco e as seguintes, do
cache; o plano de todas fica no arquivo, e a comparação usa a última. Os planos vão para
``docs/evidencias/e3/``. Precisa do Postgres no ar e de ``serie`` preenchido.

Uso::

    uv run python scripts/explain_serie.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from inflatrack.common.db import dsn_do_ambiente

RAIZ = Path(__file__).resolve().parents[1]
CONSULTA = RAIZ / "scripts" / "sql" / "explain_serie.sql"
DESTINO = RAIZ / "docs" / "evidencias" / "e3"
INDICE = "serie.fct_inflacao_mensal_consulta_idx"
EXECUCOES = 3


def _sem_comentarios(sql: str) -> str:
    return "\n".join(linha for linha in sql.splitlines() if not linha.startswith("--"))


def _medir(conexao: psycopg.Connection, consulta: str) -> list[str]:
    planos = []
    for _ in range(EXECUCOES):
        linhas = conexao.execute(f"explain (analyze, buffers) {consulta}").fetchall()
        planos.append("\n".join(linha[0] for linha in linhas))
    return planos


def _gravar(nome: str, consulta: str, planos: list[str]) -> Path:
    corpo = [f"-- {consulta.strip()}".replace("\n", "\n-- ")]
    for numero, plano in enumerate(planos, start=1):
        corpo.append(f"\n=== Execução {numero} de {len(planos)} ===\n{plano}")
    caminho = DESTINO / nome
    caminho.write_text("\n".join(corpo) + "\n", encoding="utf-8")
    return caminho


def _tempo(plano: str) -> str:
    casou = re.search(r"Execution Time: ([\d.]+) ms", plano)
    return casou[1] if casou else "?"


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dsn", default=None, help="padrão: montado do .env")
    args = parser.parse_args(argv)
    consulta = _sem_comentarios(CONSULTA.read_text(encoding="utf-8"))

    with psycopg.connect(args.dsn or dsn_do_ambiente(), autocommit=True) as conexao:
        # A cópia apaga e insere: sem isto, a medição veria linhas mortas e estatística velha.
        conexao.execute("vacuum (analyze) serie.fct_inflacao_mensal")
        (linhas,) = conexao.execute("select count(*) from serie.fct_inflacao_mensal").fetchone()
        if not linhas:
            print("serie.fct_inflacao_mensal está vazia: rode o exportar_serie antes")
            return 1
        conexao.autocommit = False
        conexao.execute(f"drop index {INDICE}")
        sem_indice = _medir(conexao, consulta)
        conexao.rollback()
        com_indice = _medir(conexao, consulta)
        conexao.rollback()

    _gravar("explain_serie_sem_indice.txt", consulta, sem_indice)
    _gravar("explain_serie_com_indice.txt", consulta, com_indice)
    print(f"{linhas} linhas em serie.fct_inflacao_mensal")
    print(f"sem índice: {[_tempo(plano) for plano in sem_indice]} ms")
    print(f"com índice: {[_tempo(plano) for plano in com_indice]} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
