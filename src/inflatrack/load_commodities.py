import duckdb
import os
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

COMMODITY_CONFIGS = {
    "WTI": {"category": "Energia", "unit": "USD/barrel", "name": "Petróleo WTI"},
    "BRENT": {"category": "Energia", "unit": "USD/barrel", "name": "Petróleo Brent"},
    "NATURAL_GAS": {"category": "Energia", "unit": "USD/MMBtu", "name": "Gás Natural"},
    "WHEAT": {"category": "Agrícola", "unit": "USD/metric ton", "name": "Trigo"},
    "CORN": {"category": "Agrícola", "unit": "USD/metric ton", "name": "Milho"},
    "COTTON": {"category": "Agrícola", "unit": "USD/metric ton", "name": "Algodão"},
    "SUGAR": {"category": "Agrícola", "unit": "cents/pound", "name": "Açúcar"},
    "COFFEE": {"category": "Agrícola", "unit": "cents/pound", "name": "Café"},
    "ALL_COMMODITIES": {"category": "Geral", "unit": "index (2016=100)", "name": "Índice Global"}
}

def get_db_path():
    base_dir = Path(os.getcwd())
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "inflatrack.duckdb"

def get_raw_dir():
    base_dir = Path(os.getcwd())
    return base_dir / "data" / "commodities_raw"

def load_data():
    db_path = get_db_path()
    raw_dir = get_raw_dir()
    
    logger.info(f"Conectando ao banco de dados: {db_path}")
    conn = duckdb.connect(str(db_path))
    
    # Atualizar a tabela de dimensões (commodity)
    logger.info("Atualizando tabela 'commodity'...")
    for symbol, config in COMMODITY_CONFIGS.items():
        conn.execute("""
            INSERT INTO commodity (symbol, name, category, unit)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (symbol) DO UPDATE SET
                name = EXCLUDED.name,
                category = EXCLUDED.category,
                unit = EXCLUDED.unit
        """, (symbol, config["name"], config["category"], config["unit"]))
    
    # Carregar todos os parquets
    parquet_pattern = str(raw_dir / "*.parquet")
    logger.info(f"Carregando dados dos arquivos parquet: {parquet_pattern}")
    
    # Verifica se existem arquivos parquet
    try:
        # Tenta contar para ver se a tabela/arquivos existem e estão legíveis
        count = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{parquet_pattern}')").fetchone()[0]
        logger.info(f"Encontrados {count} registros nos arquivos parquet.")
    except Exception as e:
        logger.warning(f"Nenhum arquivo parquet encontrado ou erro ao ler: {e}")
        return

    # Fazer o UPSERT na commodity_cotacao
    logger.info("Executando UPSERT na tabela 'commodity_cotacao'...")
    conn.execute(f"""
        INSERT INTO commodity_cotacao (symbol, data_referencia, preco)
        SELECT symbol, data_referencia, preco
        FROM read_parquet('{parquet_pattern}')
        ON CONFLICT (symbol, data_referencia) DO UPDATE SET
            preco = EXCLUDED.preco
    """)
    
    logger.info("Carga concluída com sucesso.")
    conn.close()

if __name__ == "__main__":
    load_data()
