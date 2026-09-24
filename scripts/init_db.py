import duckdb
import os
from pathlib import Path

def get_db_path():
    base_dir = Path(os.getcwd())
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "inflatrack.duckdb"

def init_db():
    db_path = get_db_path()
    sql_path = Path(os.getcwd()) / "scripts" / "setup_duckdb.sql"
    
    print(f"Inicializando banco de dados DuckDB em: {db_path}")
    conn = duckdb.connect(str(db_path))
    
    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()
        
    conn.execute(sql)
    print("Script setup_duckdb.sql executado com sucesso.")
    conn.close()

if __name__ == "__main__":
    init_db()
