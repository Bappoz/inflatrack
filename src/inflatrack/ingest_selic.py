"""Ingestão da Selic efetiva diária (SGS série 11) pelo Banco Central."""

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

from inflatrack.selic_sgs import SGSClient, SGSError

logger = logging.getLogger("inflatrack.ingest_selic")

RAW_DIR_PADRAO = Path("data/raw/bcb")
DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
SCHEMA_SQL = Path(__file__).resolve().parents[2] / "scripts" / "setup_duckdb_macro.sql"


def salvar_raw(data: list[dict], destino: Path, inicio: date, fim: date) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"selic_{inicio.isoformat()}_a_{fim.isoformat()}.json.gz"
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        json.dump(data, arquivo, ensure_ascii=False)
    return caminho


def transformar(data: list[dict], inicio: date, fim: date) -> pd.DataFrame:
    """Converte a série 11 e carrega o último valor conhecido no calendário civil."""
    if not data:
        raise ValueError("a API SGS não retornou valores da Selic")
    quadro = pd.DataFrame(data)
    if not {"data", "valor"}.issubset(quadro.columns):
        raise ValueError("resposta da API SGS sem as colunas esperadas")

    quadro["data_referencia"] = pd.to_datetime(quadro["data"], format="%d/%m/%Y")
    quadro["taxa_dia_pct"] = pd.to_numeric(quadro["valor"], errors="raise")
    quadro = quadro.sort_values("data_referencia").drop_duplicates(
        subset=["data_referencia"], keep="last"
    )
    quadro = quadro.set_index("data_referencia")[["taxa_dia_pct"]]
    datas_observadas = quadro.index

    calendario = pd.date_range(inicio, fim, freq="D")
    quadro = quadro.reindex(quadro.index.union(calendario)).sort_index().ffill()
    quadro = quadro.reindex(calendario)
    if quadro["taxa_dia_pct"].isna().any():
        raise ValueError("não há Selic anterior para preencher o início do período")
    quadro["observado"] = quadro.index.isin(datas_observadas)
    return quadro.reset_index(names="data_referencia")


def carregar(conexao: duckdb.DuckDBPyConnection, quadro: pd.DataFrame) -> int:
    conexao.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    conexao.register("carga_selic", quadro)
    conexao.execute(
        """
        INSERT INTO selic_taxa
        SELECT data_referencia, taxa_dia_pct, observado FROM carga_selic
        ON CONFLICT (data_referencia) DO UPDATE SET
            taxa_dia_pct = EXCLUDED.taxa_dia_pct,
            observado = EXCLUDED.observado
        """
    )
    return conexao.execute("SELECT count(*) FROM selic_taxa").fetchone()[0]


def executar(args: argparse.Namespace) -> int:
    inicio = date.fromisoformat(args.de)
    fim = date.fromisoformat(args.ate)
    if inicio > fim:
        raise ValueError("--de não pode ser maior que --ate")

    busca_inicio = inicio - timedelta(days=10)
    data = SGSClient().buscar_serie(11, busca_inicio.strftime("%d/%m/%Y"), fim.strftime("%d/%m/%Y"))
    raw = salvar_raw(data, Path(args.raw_dir), inicio, fim)
    logger.info("resposta crua salva em %s", raw)
    quadro = transformar(data, inicio, fim)

    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db)) as conexao:
        total = carregar(conexao, quadro)
    logger.info("%d dias processados; %d linhas em selic_taxa", len(quadro), total)
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
    except (requests.RequestException, json.JSONDecodeError, SGSError, ValueError) as erro:
        logger.error("carga da Selic abortada: %s", erro)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
