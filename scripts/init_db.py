import os
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parents[1]


def get_db_path():
    db_path = Path(os.environ.get("DBT_DUCKDB_PATH", str(RAIZ / "data/duckdb/inflatrack.duckdb")))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def init_db():
    db_path = get_db_path()
    scripts_dir = RAIZ / "scripts" / "sql"

    # Uma fonte por arquivo (setup_duckdb_clima.sql, setup_duckdb_macro.sql...). Todos
    # são idempotentes: só CREATE ... IF NOT EXISTS e CREATE OR REPLACE VIEW. PIB e
    # commodities não têm arquivo: o loader cria bronze.* com o esquema do Delta.
    sql_paths = sorted(scripts_dir.glob("setup_duckdb*.sql"))

    print(f"Inicializando banco de dados DuckDB em: {db_path}")
    with duckdb.connect(str(db_path)) as conn:
        for sql_path in sql_paths:
            conn.execute(sql_path.read_text(encoding="utf-8"))
            print(f"Script {sql_path.name} executado com sucesso.")


if __name__ == "__main__":
    init_db()
