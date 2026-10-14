"""Carga dos Parquets de Estações e Clima do INMET no DuckDB analítico compartilhado."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
from deltalake import DeltaTable

logger = logging.getLogger("inflatrack.load_clima")

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")
PARQUET_ESTACOES_PADRAO = Path("data/parquet/clima/estacoes.parquet")
PARQUET_CLIMA_PADRAO = Path("data/parquet/clima/clima_diario.parquet")
DELTA_PADRAO = Path("data/parquet/clima")
SCHEMA_SQL = Path(__file__).resolve().parents[2] / "scripts" / "setup_duckdb_clima.sql"

MODOS_CARGA = ("substitui", "so_acrescenta")


def carregar_bronze_estacoes(
    conexao: duckdb.DuckDBPyConnection,
    delta_dir: Path,
    modo: str = "substitui",
) -> int:
    """Carrega a tabela Delta clima_estacao em bronze.clima_estacao no DuckDB.

    Suporta os dois modos definidos no contrato (seção 2.3 do plano):
    - 'substitui': DELETE e INSERT em transação única.
    - 'so_acrescenta': INSERT apenas dos registros inéditos (insert-only, chave inclui valor).
    """
    if modo not in MODOS_CARGA:
        raise ValueError(f"Modo de carga inválido: {modo!r}. Escolha entre {MODOS_CARGA}")

    caminho_estacao = delta_dir / "estacao"
    if not DeltaTable.is_deltatable(str(caminho_estacao)):
        raise FileNotFoundError(f"Tabela Delta de estações não encontrada em {caminho_estacao}")

    conexao.execute(SCHEMA_SQL.read_text(encoding="utf-8"))

    dt = DeltaTable(str(caminho_estacao))
    tbl = dt.to_pyarrow_table()
    conexao.register("temp_clima_estacao_delta", tbl)

    if modo == "substitui":
        conexao.begin()
        conexao.execute("DELETE FROM bronze.clima_estacao")
        conexao.execute(
            """
            INSERT INTO bronze.clima_estacao (
                estacao_id,
                nome,
                estado,
                tipo,
                latitude,
                longitude,
                altitude_m,
                situacao,
                data_inicio_operacao,
                data_fim_operacao,
                _id_resposta,
                _fonte,
                _requisicao,
                _ingerido_em
            )
            SELECT
                estacao_id,
                nome,
                estado,
                tipo,
                latitude,
                longitude,
                altitude_m,
                situacao,
                data_inicio_operacao,
                data_fim_operacao,
                _id_resposta,
                _fonte,
                _requisicao,
                _ingerido_em
            FROM temp_clima_estacao_delta
            """
        )
        conexao.commit()
    else:  # so_acrescenta
        conexao.execute(
            """
            INSERT INTO bronze.clima_estacao (
                estacao_id,
                nome,
                estado,
                tipo,
                latitude,
                longitude,
                altitude_m,
                situacao,
                data_inicio_operacao,
                data_fim_operacao,
                _id_resposta,
                _fonte,
                _requisicao,
                _ingerido_em
            )
            SELECT
                t.estacao_id,
                t.nome,
                t.estado,
                t.tipo,
                t.latitude,
                t.longitude,
                t.altitude_m,
                t.situacao,
                t.data_inicio_operacao,
                t.data_fim_operacao,
                t._id_resposta,
                t._fonte,
                t._requisicao,
                t._ingerido_em
            FROM temp_clima_estacao_delta AS t
            WHERE NOT EXISTS (
                SELECT 1
                FROM bronze.clima_estacao AS b
                WHERE b.estacao_id = t.estacao_id
                  AND b.nome = t.nome
                  AND b.estado = t.estado
                  AND b.tipo IS NOT DISTINCT FROM t.tipo
                  AND b.situacao IS NOT DISTINCT FROM t.situacao
                  AND b.latitude IS NOT DISTINCT FROM t.latitude
                  AND b.longitude IS NOT DISTINCT FROM t.longitude
                  AND b.altitude_m IS NOT DISTINCT FROM t.altitude_m
            )
            """
        )

    conexao.unregister("temp_clima_estacao_delta")
    return conexao.execute("SELECT count(*) FROM bronze.clima_estacao").fetchone()[0]


def carregar_estacoes(conexao: duckdb.DuckDBPyConnection, parquet: Path) -> int:
    """Aplica o DDL e faz UPSERT das estações meteorológicas na tabela legada."""
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
    """Aplica o DDL e faz UPSERT das medições climáticas diárias na tabela legada."""
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
    parser.add_argument(
        "--delta-dir", default=str(DELTA_PADRAO), help="Caminho do diretório da Bronze Delta"
    )
    parser.add_argument(
        "--modo",
        choices=MODOS_CARGA,
        default="substitui",
        help="Modo de carga na Bronze: 'substitui' ou 'so_acrescenta'",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)

    delta_dir = Path(args.delta_dir)
    caminho_estacoes = Path(args.parquet_estacoes)
    caminho_clima = Path(args.parquet_clima)

    sucesso = False
    with duckdb.connect(str(db)) as conexao:
        if DeltaTable.is_deltatable(str(delta_dir / "estacao")):
            total_bronze = carregar_bronze_estacoes(conexao, delta_dir, modo=args.modo)
            logger.info(
                "Bronze Delta carregada no DuckDB (%s): %d estações em bronze.clima_estacao",
                args.modo,
                total_bronze,
            )
            sucesso = True
        else:
            logger.warning("Tabela Delta não encontrada em %s/estacao", delta_dir)

        if caminho_estacoes.is_file():
            total_est = carregar_estacoes(conexao, caminho_estacoes)
            logger.info("Carga legada concluída: %d estações em estacao_meteorologica", total_est)
            sucesso = True

        if caminho_clima.is_file():
            total_cli = carregar_clima(conexao, caminho_clima)
            logger.info("Carga legada concluída: %d medições em clima_diario", total_cli)
            sucesso = True

    if not sucesso:
        logger.error(
            "Nenhum dado encontrado para carregar em %s ou %s",
            delta_dir,
            caminho_estacoes,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
