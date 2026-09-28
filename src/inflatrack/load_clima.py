"""Carga dos Parquets de Estações e Clima do INMET no DuckDB analítico compartilhado."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

logger = logging.getLogger("inflatrack.load_clima")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
PARQUET_ESTACOES_PADRAO = Path("data/parquet/clima/estacoes.parquet")
PARQUET_CLIMA_PADRAO = Path("data/parquet/clima/clima_diario.parquet")
SCHEMA_SQL = Path(__file__).resolve().parents[2] / "scripts" / "setup_duckdb_clima.sql"


def carregar_estacoes(conexao: duckdb.DuckDBPyConnection, parquet: Path) -> int:
    """Aplica o DDL e faz UPSERT das estações meteorológicas."""
    conexao.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    conexao.execute(
        """
        INSERT INTO estacao_meteorologica (
            estacao_id, nome, estado, tipo, latitude, longitude, altitude_m, situacao, atualizado_em
        )
        SELECT
            estacao_id, nome, estado, tipo, latitude, longitude, altitude_m, situacao, now()
        FROM read_parquet(?)
        ON CONFLICT (estacao_id) DO UPDATE SET
            nome = EXCLUDED.nome,
            estado = EXCLUDED.estado,
            tipo = EXCLUDED.tipo,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            altitude_m = EXCLUDED.altitude_m,
            situacao = EXCLUDED.situacao,
            atualizado_em = now()
        """,
        [str(parquet)],
    )
    return conexao.execute("SELECT count(*) FROM estacao_meteorologica").fetchone()[0]


def carregar_clima(conexao: duckdb.DuckDBPyConnection, parquet: Path) -> int:
    """Aplica o DDL e faz UPSERT das medições climáticas diárias."""
    conexao.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    conexao.execute(
        """
        INSERT INTO clima_diario (
            estacao_id,
            data_referencia,
            temp_min,
            temp_max,
            temp_media,
            precipitacao_total_mm,
            umidade_relativa_media_pct,
            umidade_relativa_min_pct,
            observado,
            atualizado_em
        )
        SELECT
            estacao_id,
            data_referencia,
            temp_min,
            temp_max,
            temp_media,
            precipitacao_total_mm,
            umidade_relativa_media_pct,
            umidade_relativa_min_pct,
            observado,
            now()
        FROM read_parquet(?)
        ON CONFLICT (estacao_id, data_referencia) DO UPDATE SET
            temp_min = EXCLUDED.temp_min,
            temp_max = EXCLUDED.temp_max,
            temp_media = EXCLUDED.temp_media,
            precipitacao_total_mm = EXCLUDED.precipitacao_total_mm,
            umidade_relativa_media_pct = EXCLUDED.umidade_relativa_media_pct,
            umidade_relativa_min_pct = EXCLUDED.umidade_relativa_min_pct,
            observado = EXCLUDED.observado,
            atualizado_em = now()
        """,
        [str(parquet)],
    )
    return conexao.execute("SELECT count(*) FROM clima_diario").fetchone()[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PADRAO))
    parser.add_argument("--parquet-estacoes", default=str(PARQUET_ESTACOES_PADRAO))
    parser.add_argument("--parquet-clima", default=str(PARQUET_CLIMA_PADRAO))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)

    caminho_estacoes = Path(args.parquet_estacoes)
    caminho_clima = Path(args.parquet_clima)

    with duckdb.connect(str(db)) as conexao:
        if caminho_estacoes.is_file():
            total_est = carregar_estacoes(conexao, caminho_estacoes)
            logger.info(
                "Carga concluída: %d estações cadastradas em estacao_meteorologica", total_est
            )
        else:
            logger.warning("Parquet de estações não encontrado em %s (ignorado)", caminho_estacoes)

        if caminho_clima.is_file():
            total_cli = carregar_clima(conexao, caminho_clima)
            logger.info("Carga concluída: %d medições registradas em clima_diario", total_cli)
        else:
            logger.warning("Parquet de medições não encontrado em %s (ignorado)", caminho_clima)

    return 0


if __name__ == "__main__":
    sys.exit(main())
