import argparse
import os
import json
import gzip
import pandas as pd
import duckdb
from datetime import datetime
from pathlib import Path
from inflatrack.selic_sgs import SGSClient
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("etl_selic")

def get_dir(layer: str):
    base_dir = Path(os.getcwd())
    data_dir = base_dir / "data" / layer
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

def salvar_raw_selic(data: list, dt_inicio_iso: str, dt_fim_iso: str):
    filepath = get_dir("bcb_raw") / f"selic_{dt_inicio_iso}_a_{dt_fim_iso}.json.gz"
    with gzip.open(filepath, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    logger.info(f"Arquivo RAW salvo em {filepath}")
    return filepath

def carregar_duckdb(df: pd.DataFrame):
    db_path = Path(os.getcwd()) / "data" / "inflatrack.duckdb"
    logger.info(f"Conectando ao banco analítico: {db_path}")
    conn = duckdb.connect(str(db_path))
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS selic_taxa (
            data_referencia DATE PRIMARY KEY,
            taxa_efetiva DOUBLE
        );
    """)
    
    try:
        conn.execute("CREATE TEMP TABLE temp_df AS SELECT * FROM df")
        conn.execute("""
            INSERT INTO selic_taxa (data_referencia, taxa_efetiva)
            SELECT data_referencia, taxa_efetiva FROM temp_df
            ON CONFLICT (data_referencia) DO UPDATE SET
                taxa_efetiva = EXCLUDED.taxa_efetiva
        """)
        count = conn.execute("SELECT COUNT(*) FROM selic_taxa").fetchone()[0]
        logger.info(f"Selic carregada no DuckDB! Total de linhas na tabela: {count}")
    except Exception as e:
        logger.warning(f"Erro ao carregar Selic: {e}")
    finally:
        conn.close()

def processar_bronze_e_carregar(raw_filepath: Path):
    with gzip.open(raw_filepath, "rt", encoding="utf-8") as f:
        df = pd.DataFrame(json.load(f))
    
    if df.empty:
        logger.warning("Nenhum dado encontrado.")
        return
        
    df["data_referencia"] = pd.to_datetime(df["data"], format="%d/%m/%Y").dt.date
    df["taxa_efetiva"] = df["valor"].astype(float)
    df = df[["data_referencia", "taxa_efetiva"]]
    
    df["data_referencia"] = pd.to_datetime(df["data_referencia"])
    df = df.drop_duplicates(subset=["data_referencia"], keep="last")
    df.set_index("data_referencia", inplace=True)
    df_completo = df.resample("D").ffill().reset_index()
    
    logger.info(f"Transformação Bronze em memória concluída: {len(df_completo)} dias processados.")
    carregar_duckdb(df_completo)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--de", required=True, help="Formato ISO (AAAA-MM-DD)")
    parser.add_argument("--ate", required=True, help="Formato ISO (AAAA-MM-DD)")
    args = parser.parse_args()
    
    dt_de = datetime.strptime(args.de, "%Y-%m-%d").strftime("%d/%m/%Y")
    dt_ate = datetime.strptime(args.ate, "%Y-%m-%d").strftime("%d/%m/%Y")
    
    client = SGSClient()
    payload = client.buscar_serie(11, dt_de, dt_ate)
    raw_path = salvar_raw_selic(payload, args.de, args.ate)
    processar_bronze_e_carregar(raw_path)

if __name__ == "__main__":
    main()
