import duckdb
import os
import logging
from pathlib import Path

logger = logging.getLogger("load_dolar")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_data():
    base_dir = Path(os.getcwd())
    db_path = base_dir / "data" / "inflatrack.duckdb"
    bronze_dir = base_dir / "data" / "bcb_bronze"
    
    logger.info(f"Conectando ao banco analítico: {db_path}")
    conn = duckdb.connect(str(db_path))
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dolar_cotacao (
            data_referencia DATE PRIMARY KEY,
            cotacaoCompra DOUBLE,
            cotacaoVenda DOUBLE
        );
    """)
    
    dolar_pattern = str(bronze_dir / "dolar_*.parquet")
    try:
        conn.execute(f"""
            INSERT INTO dolar_cotacao (data_referencia, cotacaoCompra, cotacaoVenda)
            SELECT data_referencia, cotacaoCompra, cotacaoVenda
            FROM read_parquet('{dolar_pattern}')
            ON CONFLICT (data_referencia) DO UPDATE SET
                cotacaoCompra = EXCLUDED.cotacaoCompra,
                cotacaoVenda = EXCLUDED.cotacaoVenda
        """)
        count = conn.execute("SELECT COUNT(*) FROM dolar_cotacao").fetchone()[0]
        logger.info(f"Dólar carregado no DuckDB! Total: {count} registros")
    except Exception as e:
        logger.warning(f"Erro ao carregar Dólar: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    load_data()
