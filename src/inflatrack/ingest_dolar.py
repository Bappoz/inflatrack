import argparse
import os
import json
import gzip
import pandas as pd
from datetime import datetime
from pathlib import Path
from inflatrack.dolar_olinda import OlindaClient
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ingest_dolar")

def get_dir(layer: str):
    base_dir = Path(os.getcwd())
    data_dir = base_dir / "data" / layer
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

def salvar_raw_dolar(data: list, dt_inicio_iso: str, dt_fim_iso: str):
    filepath = get_dir("bcb_raw") / f"dolar_{dt_inicio_iso}_a_{dt_fim_iso}.json.gz"
    with gzip.open(filepath, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    logger.info(f"Arquivo RAW salvo em {filepath}")
    return filepath

def processar_bronze_dolar(raw_filepath: Path):
    with gzip.open(raw_filepath, "rt", encoding="utf-8") as f:
        df = pd.DataFrame(json.load(f))
    
    if df.empty:
        logger.warning("Nenhum dado encontrado.")
        return
        
    df["data_referencia"] = pd.to_datetime(df["dataHoraCotacao"]).dt.date
    df = df[["data_referencia", "cotacaoCompra", "cotacaoVenda"]]
    
    df["data_referencia"] = pd.to_datetime(df["data_referencia"])
    df = df.drop_duplicates(subset=["data_referencia"], keep="last")
    df.set_index("data_referencia", inplace=True)
    
    # Preenche furos de finais de semana e feriados com o valor do dia anterior (Sexta)
    df_completo = df.resample("D").ffill().reset_index()
    
    output_file = get_dir("bcb_bronze") / "dolar_tratado.parquet"
    df_completo.to_parquet(output_file, index=False)
    logger.info(f"Bronze Dólar salvo: {len(df_completo)} dias em {output_file}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--de", required=True, help="Formato ISO (AAAA-MM-DD)")
    parser.add_argument("--ate", required=True, help="Formato ISO (AAAA-MM-DD)")
    args = parser.parse_args()
    
    # Converte ISO para Padrão Olinda (MM-DD-YYYY)
    dt_de = datetime.strptime(args.de, "%Y-%m-%d").strftime("%m-%d-%Y")
    dt_ate = datetime.strptime(args.ate, "%Y-%m-%d").strftime("%m-%d-%Y")
    
    client = OlindaClient()
    payload = client.buscar_dolar(dt_de, dt_ate)
    raw_path = salvar_raw_dolar(payload, args.de, args.ate)
    processar_bronze_dolar(raw_path)

if __name__ == "__main__":
    main()
