import duckdb
import os
from pathlib import Path

def get_db_path():
    base_dir = Path(os.getcwd())
    db_dir = base_dir / "data" / "duckdb"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "inflatrack.duckdb"

def init_db():
    db_path = get_db_path()
    scripts_dir = Path(os.getcwd()) / "scripts"

    # Uma fonte por arquivo (setup_duckdb.sql = commodities,
    # setup_duckdb_pib.sql = contas nacionais). Todos são idempotentes:
    # só CREATE ... IF NOT EXISTS e CREATE OR REPLACE VIEW.
    sql_paths = sorted(scripts_dir.glob("setup_duckdb*.sql"))

    print(f"Inicializando banco de dados DuckDB em: {db_path}")
    conn = duckdb.connect(str(db_path))

    for sql_path in sql_paths:
        conn.execute(sql_path.read_text(encoding="utf-8"))
        print(f"Script {sql_path.name} executado com sucesso.")

    conn.close()

if __name__ == "__main__":
    init_db()
