"""Carga do Parquet de Salário Mínimo (DIEESE) no DuckDB analítico compartilhado."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
from deltalake import DeltaTable

logger = logging.getLogger("inflatrack.load_salario_minimo")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
PARQUET_PADRAO = Path("data/parquet/dieese/salario_minimo.parquet")
DELTA_PADRAO = Path("data/parquet/salario_minimo")
SCHEMA_SQL = Path(__file__).resolve().parents[2] / "scripts" / "setup_duckdb_salario_minimo.sql"

MODOS_CARGA = ("substitui", "so_acrescenta")


def carregar_bronze(
    conexao: duckdb.DuckDBPyConnection,
    delta_dir: Path,
    modo: str = "substitui",
) -> int:
    """Carrega a tabela Delta salario_minimo_mes em bronze.salario_minimo_mes no DuckDB.

    Suporta os dois modos definidos no contrato (seção 2.3 do plano):
    - 'substitui': DELETE e INSERT em transação única.
    - 'so_acrescenta': INSERT apenas dos registros inéditos (insert-only, chave inclui valor).
    """
    if modo not in MODOS_CARGA:
        raise ValueError(f"Modo de carga inválido: {modo!r}. Escolha entre {MODOS_CARGA}")

    caminho_mes = delta_dir / "mes"
    if not DeltaTable.is_deltatable(str(caminho_mes)):
        raise FileNotFoundError(f"Tabela Delta de meses não encontrada em {caminho_mes}")

    conexao.execute(SCHEMA_SQL.read_text(encoding="utf-8"))

    dt = DeltaTable(str(caminho_mes))
    tbl = dt.to_pyarrow_table()
    conexao.register("temp_salario_minimo_delta", tbl)

    if modo == "substitui":
        conexao.begin()
        conexao.execute("DELETE FROM bronze.salario_minimo_mes")
        conexao.execute(
            """
            INSERT INTO bronze.salario_minimo_mes (
                ano_mes,
                data_referencia,
                ano,
                mes,
                salario_nominal,
                salario_necessario,
                _id_resposta,
                _fonte,
                _requisicao,
                _ingerido_em
            )
            SELECT
                ano_mes,
                data_referencia,
                ano,
                mes,
                salario_nominal,
                salario_necessario,
                _id_resposta,
                _fonte,
                _requisicao,
                _ingerido_em
            FROM temp_salario_minimo_delta
            """
        )
        conexao.commit()
    else:  # so_acrescenta
        conexao.execute(
            """
            INSERT INTO bronze.salario_minimo_mes (
                ano_mes,
                data_referencia,
                ano,
                mes,
                salario_nominal,
                salario_necessario,
                _id_resposta,
                _fonte,
                _requisicao,
                _ingerido_em
            )
            SELECT
                t.ano_mes,
                t.data_referencia,
                t.ano,
                t.mes,
                t.salario_nominal,
                t.salario_necessario,
                t._id_resposta,
                t._fonte,
                t._requisicao,
                t._ingerido_em
            FROM temp_salario_minimo_delta AS t
            WHERE NOT EXISTS (
                SELECT 1
                FROM bronze.salario_minimo_mes AS b
                WHERE b.ano_mes = t.ano_mes
                  AND b.salario_nominal IS NOT DISTINCT FROM t.salario_nominal
                  AND b.salario_necessario IS NOT DISTINCT FROM t.salario_necessario
            )
            """
        )

    conexao.unregister("temp_salario_minimo_delta")
    return conexao.execute("SELECT count(*) FROM bronze.salario_minimo_mes").fetchone()[0]


def carregar(conexao: duckdb.DuckDBPyConnection, parquet: Path) -> int:
    """Aplica o esquema DDL e faz UPSERT idempotente por ano_mes na tabela legada."""
    conexao.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    conexao.execute(
        """
        INSERT INTO salario_minimo (
            ano_mes,
            data_referencia,
            ano,
            mes,
            salario_nominal,
            salario_necessario,
            multiplo_necessario_nominal,
            atualizado_em
        )
        SELECT
            ano_mes,
            data_referencia,
            ano,
            mes,
            salario_nominal,
            salario_necessario,
            multiplo_necessario_nominal,
            now()
        FROM read_parquet(?)
        ON CONFLICT (ano_mes) DO UPDATE SET
            data_referencia = EXCLUDED.data_referencia,
            ano = EXCLUDED.ano,
            mes = EXCLUDED.mes,
            salario_nominal = EXCLUDED.salario_nominal,
            salario_necessario = EXCLUDED.salario_necessario,
            multiplo_necessario_nominal = EXCLUDED.multiplo_necessario_nominal,
            atualizado_em = now()
        """,
        [str(parquet)],
    )
    return conexao.execute("SELECT count(*) FROM salario_minimo").fetchone()[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PADRAO), help="Caminho do banco DuckDB")
    parser.add_argument("--parquet", default=str(PARQUET_PADRAO), help="Caminho do Parquet legado")
    parser.add_argument(
        "--delta-dir", default=str(DELTA_PADRAO), help="Caminho do diretório da Bronze Delta"
    )
    parser.add_argument(
        "--modo",
        choices=MODOS_CARGA,
        default="substitui",
        help="Modo de carga na Bronze: 'substitui' ou 'so_acrescenta'",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)

    delta_dir = Path(args.delta_dir)
    parquet = Path(args.parquet)

    sucesso = False
    with duckdb.connect(str(db)) as conexao:
        if DeltaTable.is_deltatable(str(delta_dir / "mes")):
            total_bronze = carregar_bronze(conexao, delta_dir, modo=args.modo)
            logger.info(
                "Bronze Delta carregada no DuckDB (%s): %d meses em bronze.salario_minimo_mes",
                args.modo,
                total_bronze,
            )
            sucesso = True
        else:
            logger.warning("Tabela Delta não encontrada em %s/mes", delta_dir)

        if parquet.is_file():
            total_legado = carregar(conexao, parquet)
            logger.info("Carga legada concluída: %d meses em salario_minimo", total_legado)
            sucesso = True

    if not sucesso:
        logger.error("Nenhum dado encontrado para carregar em %s ou %s", delta_dir, parquet)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
