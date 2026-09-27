"""Ingestão da cotação diária do dólar comercial pela API Olinda/PTAX."""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import requests

from inflatrack.dolar_olinda import OlindaClient, OlindaError

logger = logging.getLogger("inflatrack.ingest_dolar")

RAW_DIR_PADRAO = Path("data/raw/bcb")
DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
SCHEMA_SQL = Path(__file__).resolve().parents[2] / "scripts" / "setup_duckdb_macro.sql"


def salvar_raw(data: list[dict], destino: Path, inicio: date, fim: date) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"dolar_{inicio.isoformat()}_a_{fim.isoformat()}.json.gz"
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        json.dump(data, arquivo, ensure_ascii=False)
    return caminho


def transformar(data: list[dict], inicio: date, fim: date) -> pd.DataFrame:
    """Seleciona o último boletim do dia e carrega o último valor conhecido."""
    if not data:
        raise ValueError("a API Olinda não retornou cotações")
    quadro = pd.DataFrame(data)
    obrigatorias = {"dataHoraCotacao", "cotacaoCompra", "cotacaoVenda"}
    if not obrigatorias.issubset(quadro.columns):
        raise ValueError("resposta da API Olinda sem as colunas esperadas")

    quadro["instante"] = pd.to_datetime(quadro["dataHoraCotacao"], errors="raise")
    quadro["data_referencia"] = quadro["instante"].dt.normalize()
    quadro = quadro.sort_values("instante").drop_duplicates(subset=["data_referencia"], keep="last")
    quadro = quadro.set_index("data_referencia")
    quadro = quadro.rename(
        columns={"cotacaoCompra": "cotacao_compra", "cotacaoVenda": "cotacao_venda"}
    )[["cotacao_compra", "cotacao_venda"]]
    datas_observadas = quadro.index

    calendario = pd.date_range(inicio, fim, freq="D")
    quadro = quadro.reindex(quadro.index.union(calendario)).sort_index().ffill()
    quadro = quadro.reindex(calendario)
    if quadro[["cotacao_compra", "cotacao_venda"]].isna().any().any():
        raise ValueError("não há cotação anterior para preencher o início do período")
    quadro["observado"] = quadro.index.isin(datas_observadas)
    return quadro.reset_index(names="data_referencia")


def carregar(conexao: duckdb.DuckDBPyConnection, quadro: pd.DataFrame) -> int:
    conexao.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    conexao.register("carga_dolar", quadro)
    conexao.execute(
        """
        INSERT INTO dolar_cotacao
        SELECT data_referencia, cotacao_compra, cotacao_venda, observado FROM carga_dolar
        ON CONFLICT (data_referencia) DO UPDATE SET
            cotacao_compra = EXCLUDED.cotacao_compra,
            cotacao_venda = EXCLUDED.cotacao_venda,
            observado = EXCLUDED.observado
        """
    )
    return conexao.execute("SELECT count(*) FROM dolar_cotacao").fetchone()[0]


def executar(args: argparse.Namespace) -> int:
    inicio = date.fromisoformat(args.de)
    fim = date.fromisoformat(args.ate)
    if inicio > fim:
        raise ValueError("--de não pode ser maior que --ate")

    # O lookback fornece o valor anterior para preencher feriado/fim de semana no início.
    busca_inicio = inicio - timedelta(days=10)
    data = OlindaClient().buscar_dolar(busca_inicio.strftime("%m-%d-%Y"), fim.strftime("%m-%d-%Y"))
    raw = salvar_raw(data, Path(args.raw_dir), inicio, fim)
    logger.info("resposta crua salva em %s", raw)
    quadro = transformar(data, inicio, fim)

    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db)) as conexao:
        total = carregar(conexao, quadro)
    logger.info("%d dias processados; %d linhas em dolar_cotacao", len(quadro), total)
    return len(quadro)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--de", default="2020-01-01", help="AAAA-MM-DD")
    parser.add_argument("--ate", default=date.today().isoformat(), help="AAAA-MM-DD")
    parser.add_argument("--raw-dir", default=str(RAW_DIR_PADRAO))
    parser.add_argument("--db", default=str(DB_PADRAO))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        executar(args)
    except (requests.RequestException, json.JSONDecodeError, OlindaError, ValueError) as erro:
        logger.error("carga do dólar abortada: %s", erro)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
