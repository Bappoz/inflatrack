import argparse
import os
import pandas as pd
from pathlib import Path
from inflatrack.alphavantage import AlphaVantageClient
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

COMMODITY_CONFIGS = {
    "WTI": {"interval": "daily", "category": "Energia", "unit": "USD/barrel", "name": "Petróleo WTI"},
    "BRENT": {"interval": "daily", "category": "Energia", "unit": "USD/barrel", "name": "Petróleo Brent"},
    "NATURAL_GAS": {"interval": "daily", "category": "Energia", "unit": "USD/MMBtu", "name": "Gás Natural"},
    "WHEAT": {"interval": "monthly", "category": "Agrícola", "unit": "USD/metric ton", "name": "Trigo"},
    "CORN": {"interval": "monthly", "category": "Agrícola", "unit": "USD/metric ton", "name": "Milho"},
    "COTTON": {"interval": "monthly", "category": "Agrícola", "unit": "USD/metric ton", "name": "Algodão"},
    "SUGAR": {"interval": "monthly", "category": "Agrícola", "unit": "cents/pound", "name": "Açúcar"},
    "COFFEE": {"interval": "monthly", "category": "Agrícola", "unit": "cents/pound", "name": "Café"},
    "ALL_COMMODITIES": {"interval": "monthly", "category": "Geral", "unit": "index (2016=100)", "name": "Índice Global"}
}

def get_data_dir():
    # Caminho base do projeto
    base_dir = Path(os.getcwd())
    data_dir = base_dir / "data" / "commodities_raw"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

def process_response(symbol: str, data: dict) -> pd.DataFrame:
    # A estrutura do JSON de commodities é:
    # {
    #   "name": "...",
    #   "interval": "...",
    #   "unit": "...",
    #   "data": [{"date": "2023-01-01", "value": "78.16"}, ...]
    # }
    if "data" not in data:
        raise ValueError(f"Formato inesperado para {symbol}: {data.keys()}")
        
    records = data["data"]
    
    # Filtra valores que podem vir como '.' em vez de um número válido
    valid_records = [r for r in records if r["value"] != "."]
    
    df = pd.DataFrame(valid_records)
    if df.empty:
        logger.warning(f"Sem dados válidos para {symbol}.")
        return df
        
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["value"] = df["value"].astype(float)
    df["symbol"] = symbol
    df = df.rename(columns={"date": "data_referencia", "value": "preco"})
    
    # Reordenar colunas
    return df[["symbol", "data_referencia", "preco"]]

def ingest_commodity(client: AlphaVantageClient, symbol: str, modo: str):
    config = COMMODITY_CONFIGS.get(symbol)
    if not config:
        raise ValueError(f"Commodity {symbol} não configurada.")
        
    logger.info(f"Iniciando ingestão de {symbol} no modo {modo}")
    
    try:
        data = client.buscar_commodity(function=symbol, interval=config["interval"])
        df = process_response(symbol, data)
        
        if df.empty:
            return
            
        output_file = get_data_dir() / f"{symbol.lower()}_{modo}.parquet"
        df.to_parquet(output_file, index=False)
        logger.info(f"Salvo {len(df)} registros em {output_file}")
        
    except Exception as e:
        logger.error(f"Erro ao ingerir {symbol}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Ingestão de Commodities da Alpha Vantage")
    parser.add_argument("--commodity", type=str, help="Symbol da commodity ou 'ALL' para todas")
    parser.add_argument("--modo", type=str, choices=["historico", "incremental"], default="historico")
    
    args = parser.parse_args()
    
    client = AlphaVantageClient()
    
    if args.commodity == "ALL" or not args.commodity:
        symbols = list(COMMODITY_CONFIGS.keys())
    else:
        symbols = [args.commodity]
        
    for symbol in symbols:
        ingest_commodity(client, symbol, args.modo)

if __name__ == "__main__":
    main()
