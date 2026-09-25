import argparse
import os
import json
import gzip
import pandas as pd
import duckdb
from datetime import datetime
from pathlib import Path
from inflatrack.dolar_olinda import OlindaClient
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("etl_dolar")

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

def carregar_duckdb(df: pd.DataFrame):
    db_path = Path(os.getcwd()) / "data" / "inflatrack.duckdb"
    logger.info(f"Conectando ao banco analítico: {db_path}")
    conn = duckdb.connect(str(db_path))
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dolar_cotacao (
            data_referencia DATE PRIMARY KEY,
            cotacaoCompra DOUBLE,
            cotacaoVenda DOUBLE
        );
    """)
    
    try:
        # DuckDB lê o df (Dataframe do Pandas) nativamente pela variável
        conn.execute("CREATE TEMP TABLE temp_df AS SELECT * FROM df")
        conn.execute("""
            INSERT INTO dolar_cotacao (data_referencia, cotacaoCompra, cotacaoVenda)
            SELECT data_referencia, cotacaoCompra, cotacaoVenda FROM temp_df
            ON CONFLICT (data_referencia) DO UPDATE SET
                cotacaoCompra = EXCLUDED.cotacaoCompra,
                cotacaoVenda = EXCLUDED.cotacaoVenda
        """)
        count = conn.execute("SELECT COUNT(*) FROM dolar_cotacao").fetchone()[0]
        logger.info(f"Dólar carregado no DuckDB! Total de linhas na tabela: {count}")
    except Exception as e:
        logger.warning(f"Erro ao carregar Dólar: {e}")
    finally:
        conn.close()

def processar_bronze_e_carregar(raw_filepath: Path):
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
    
    # Preenche furos de finais de semana e feriados em memória
    df_completo = df.resample("D").ffill().reset_index()
    logger.info(f"Transformação Bronze em memória concluída: {len(df_completo)} dias processados.")
    
    # Carrega direto pro DuckDB (sem gerar arquivo .parquet intermediário)
    carregar_duckdb(df_completo)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--de", required=True, help="Formato ISO (AAAA-MM-DD)")
    parser.add_argument("--ate", required=True, help="Formato ISO (AAAA-MM-DD)")
    args = parser.parse_args()
    
    dt_de = datetime.strptime(args.de, "%Y-%m-%d").strftime("%m-%d-%Y")
    dt_ate = datetime.strptime(args.ate, "%Y-%m-%d").strftime("%m-%d-%Y")
    
    client = OlindaClient()
    payload = client.buscar_dolar(dt_de, dt_ate)
    raw_path = salvar_raw_dolar(payload, args.de, args.ate)
    processar_bronze_e_carregar(raw_path)

if __name__ == "__main__":
    main()
