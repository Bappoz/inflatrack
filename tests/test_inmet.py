from pathlib import Path

import duckdb
import pytest

from inflatrack.inmet import (
    InmetError,
    transformar_clima_diario,
    transformar_estacoes,
)
from inflatrack.load_clima import carregar_clima, carregar_estacoes


def test_transformar_estacoes_valido() -> None:
    payload = [
        {
            "CD_ESTACAO": "A001",
            "DC_NOME": "BRASILIA",
            "SG_ESTADO": "DF",
            "TP_ESTACAO": "Automatica",
            "VL_LATITUDE": "-15.7894",
            "VL_LONGITUDE": "-47.9258",
            "VL_ALTITUDE": "1159.5",
            "CD_SITUACAO": "Operante",
        },
        {
            "CD_ESTACAO": "A472",
            "DC_NOME": "ACAJUTIBA",
            "SG_ESTADO": "BA",
            "TP_ESTACAO": "Automatica",
            "VL_LATITUDE": "-11.6544",
            "VL_LONGITUDE": "-38.0158",
            "VL_ALTITUDE": "182.0",
            "CD_SITUACAO": "Operante",
        },
    ]

    df = transformar_estacoes(payload)
    assert len(df) == 2
    assert df["estacao_id"].tolist() == ["A001", "A472"]
    assert df.loc[df["estacao_id"] == "A001", "latitude"].item() == pytest.approx(-15.7894)
    assert df.loc[df["estacao_id"] == "A472", "estado"].item() == "BA"


def test_transformar_clima_diario_valido() -> None:
    payload = [
        {
            "CD_ESTACAO": "A001",
            "DT_MEDICAO": "2024-09-01",
            "TEM_MIN": "16.4",
            "TEM_MAX": "31.2",
            "TEM_MED": "23.8",
            "CHUVA": "0.0",
            "UMD_MED": "42.0",
            "UMD_MIN": "20.0",
        },
        {
            "CD_ESTACAO": "A001",
            "DT_MEDICAO": "2024-09-02",
            "TEM_MIN": "17.0",
            "TEM_MAX": "32.0",
            # Sem TEM_MED explícito -> deve derivar média simples
            "CHUVA": "12.5",
            "UMD_MED": "55.0",
            "UMD_MIN": "28.0",
        },
    ]

    df = transformar_clima_diario(payload)
    assert len(df) == 2
    assert df.loc[df["data_referencia"].astype(str) == "2024-09-01", "temp_media"].item() == 23.8
    assert df.loc[df["data_referencia"].astype(str) == "2024-09-02", "temp_media"].item() == 24.5
    assert (
        df.loc[df["data_referencia"].astype(str) == "2024-09-02", "precipitacao_total_mm"].item()
        == 12.5
    )


def test_transformar_rejeita_payload_invalido() -> None:
    with pytest.raises(InmetError):
        transformar_estacoes([])

    with pytest.raises(InmetError):
        transformar_clima_diario([])


def test_carregar_estacoes_e_clima_upsert_idempotente(tmp_path: Path) -> None:
    parquet_estacoes = tmp_path / "estacoes.parquet"
    parquet_clima = tmp_path / "clima_diario.parquet"

    transformar_estacoes(
        [
            {
                "CD_ESTACAO": "A001",
                "DC_NOME": "BRASILIA",
                "SG_ESTADO": "DF",
                "TP_ESTACAO": "Automatica",
            }
        ]
    ).to_parquet(parquet_estacoes)

    transformar_clima_diario(
        [
            {
                "CD_ESTACAO": "A001",
                "DT_MEDICAO": "2024-09-01",
                "TEM_MIN": 15.0,
                "TEM_MAX": 30.0,
                "CHUVA": 0.0,
            }
        ]
    ).to_parquet(parquet_clima)

    with duckdb.connect(":memory:") as conexao:
        # Carga inicial
        assert carregar_estacoes(conexao, parquet_estacoes) == 1
        assert carregar_clima(conexao, parquet_clima) == 1

        # Carga reexecutada (idempotência)
        assert carregar_estacoes(conexao, parquet_estacoes) == 1
        assert carregar_clima(conexao, parquet_clima) == 1

        res_clima = conexao.execute(
            "SELECT temp_min, temp_max, precipitacao_total_mm "
            "FROM clima_diario WHERE estacao_id = 'A001'"
        ).fetchone()
        assert res_clima == (15.0, 30.0, 0.0)
