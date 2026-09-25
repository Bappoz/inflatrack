import duckdb
import os
import logging
from pathlib import Path

logger = logging.getLogger("load_selic")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_data():
    base_dir = Path(os.getcwd())
    db_path = base_dir / "data" / "inflatrack.duckdb"
    bronze_dir = base_dir / "data" / "bcb_bronze"
    
    logger.info(f"Conectando ao banco analítico: {db_path}")
    conn = duckdb.connect(str(db_path))
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS selic_taxa (
            data_referencia DATE PRIMARY KEY,
            taxa_efetiva DOUBLE
        );
    """)
    
    selic_pattern = str(bronze_dir / "selic_*.parquet")
    try:
        conn.execute(f"""
            INSERT INTO selic_taxa (data_referencia, taxa_efetiva)
            SELECT data_referencia, taxa_efetiva
            FROM read_parquet('{selic_pattern}')
            ON CONFLICT (data_referencia) DO UPDATE SET
                taxa_efetiva = EXCLUDED.taxa_efetiva
        """)
        count = conn.execute("SELECT COUNT(*) FROM selic_taxa").fetchone()[0]
        logger.info(f"Selic carregada no DuckDB! Total: {count} registros")
    except Exception as e:
        logger.warning(f"Erro ao carregar Selic: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    load_data()
