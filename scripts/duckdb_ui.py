"""Sobe a interface web embutida do DuckDB (extensão `ui`) sobre data/duckdb/inflatrack.duckdb.

Abre o banco em modo somente leitura: não disputa o lock com os loaders e com o dbt. Se um run do
Dagster estiver escrevendo no arquivo naquele instante, a conexão falha; espere o run acabar.
Uso: `just duckdb-ui`; interface em http://localhost:4213. Ctrl+C encerra.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb

BANCO = Path(__file__).resolve().parents[1] / "data" / "duckdb" / "inflatrack.duckdb"


def main() -> int:
    if not BANCO.exists():
        print(f"Banco não encontrado: {BANCO}. Rode um loader antes (ex.: just clima-load).")
        return 1
    # A interface precisa criar um banco em memória (`localmemdb`), o que uma conexão aberta com
    # read_only=True proíbe. Por isso a conexão principal é em memória e o arquivo entra anexado
    # como READ_ONLY: a UI funciona e o arquivo continua protegido contra escrita.
    conexao = duckdb.connect()
    try:
        conexao.sql(f"ATTACH '{BANCO.as_posix()}' AS inflatrack (READ_ONLY)")
    except duckdb.IOException as erro:
        print(f"Não abriu o DuckDB (um run do Dagster está escrevendo?): {erro}")
        return 1
    conexao.sql("USE inflatrack; INSTALL ui; LOAD ui;")
    (mensagem,) = conexao.sql("CALL start_ui_server()").fetchone()
    print(f"{mensagem} Banco somente leitura. Ctrl+C para encerrar.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        conexao.sql("CALL stop_ui_server()")
        conexao.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
