"""Carga da Cesta Básica do PROCON no DuckDB analítico compartilhado."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import duckdb
from deltalake import DeltaTable

logger = logging.getLogger("inflatrack.load_procon")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
DELTA_PADRAO = Path("data/parquet/procon")
SCHEMA_SQL = Path(__file__).resolve().parents[3] / "scripts" / "sql" / "setup_duckdb_procon.sql"

MODOS_CARGA = ("substitui", "so_acrescenta")


def carregar_bronze(
    conexao: duckdb.DuckDBPyConnection,
    delta_dir: Path = DELTA_PADRAO,
    modo: str = "substitui",
) -> int:
    """Carrega a tabela Delta procon_cesta_basica em bronze.procon_cesta_basica no DuckDB.

    Suporta os dois modos definidos no contrato da Bronze:
    - 'substitui': DELETE e INSERT em transação única.
    - 'so_acrescenta': INSERT apenas dos registros inéditos (insert-only).
    """
    if modo not in MODOS_CARGA:
        raise ValueError(f"Modo de carga inválido: {modo!r}. Escolha entre {MODOS_CARGA}")

    caminho_tabela = delta_dir / "cesta_basica"
    if not DeltaTable.is_deltatable(str(caminho_tabela)):
        raise FileNotFoundError(f"Tabela Delta de cesta básica não encontrada em {caminho_tabela}")

    conexao.execute(SCHEMA_SQL.read_text(encoding="utf-8"))

    dt = DeltaTable(str(caminho_tabela))
    tbl = dt.to_pyarrow_table()
    conexao.register("temp_procon_delta", tbl)

    if modo == "substitui":
        conexao.begin()
        conexao.execute("DELETE FROM bronze.procon_cesta_basica")
        conexao.execute(
            """
            INSERT INTO bronze.procon_cesta_basica (
                data_pesquisa,
                produto,
                unidade,
                preco_medio,
                preco_minimo,
                preco_maximo,
                praca,
                codigo_subitem_ipca,
                _id_resposta,
                _fonte,
                _requisicao,
                _ingerido_em
            )
            SELECT
                data_pesquisa,
                produto,
                unidade,
                preco_medio,
                preco_minimo,
                preco_maximo,
                praca,
                codigo_subitem_ipca,
                _id_resposta,
                _fonte,
                _requisicao,
                _ingerido_em
            FROM temp_procon_delta
            """
        )
        conexao.commit()
    else:  # so_acrescenta
        conexao.execute(
            """
            INSERT INTO bronze.procon_cesta_basica (
                data_pesquisa,
                produto,
                unidade,
                preco_medio,
                preco_minimo,
                preco_maximo,
                praca,
                codigo_subitem_ipca,
                _id_resposta,
                _fonte,
                _requisicao,
                _ingerido_em
            )
            SELECT
                t.data_pesquisa,
                t.produto,
                t.unidade,
                t.preco_medio,
                t.preco_minimo,
                t.preco_maximo,
                t.praca,
                t.codigo_subitem_ipca,
                t._id_resposta,
                t._fonte,
                t._requisicao,
                t._ingerido_em
            FROM temp_procon_delta AS t
            WHERE NOT EXISTS (
                SELECT 1
                FROM bronze.procon_cesta_basica AS b
                WHERE b.data_pesquisa = t.data_pesquisa
                  AND b.produto = t.produto
                  AND b.praca = t.praca
                  AND b.preco_medio = t.preco_medio
            )
            """
        )

    linhas_totais = conexao.execute("SELECT count(*) FROM bronze.procon_cesta_basica").fetchone()[0]
    return linhas_totais


def main() -> None:
    parser = argparse.ArgumentParser(description="Carrega Cesta Básica do PROCON no DuckDB")
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PADRAO,
        help="Caminho do arquivo DuckDB",
    )
    parser.add_argument(
        "--delta-dir",
        type=Path,
        default=DELTA_PADRAO,
        help="Diretório da tabela Delta do PROCON",
    )
    parser.add_argument(
        "--modo",
        choices=MODOS_CARGA,
        default="substitui",
        help="Estratégia de carga na tabela Bronze ('substitui' ou 'so_acrescenta')",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    args.db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(args.db)) as conexao:
        total = carregar_bronze(conexao, delta_dir=args.delta_dir, modo=args.modo)
        print(f"Sucesso: bronze.procon_cesta_basica contém {total} linhas (modo: {args.modo})")


if __name__ == "__main__":
    main()
