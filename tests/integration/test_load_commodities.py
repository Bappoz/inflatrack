from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from inflatrack.load_commodities import load_data


@pytest.fixture
def repo_limpo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Diretório sem DuckDB, como numa máquina recém-clonada (a carga usa caminhos do cwd)."""
    monkeypatch.chdir(tmp_path)
    parquet_dir = tmp_path / "data" / "parquet"
    parquet_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "symbol": ["WTI", "WTI"],
            "data_referencia": [date(2026, 9, 1), date(2026, 9, 2)],
            "preco": [70.5, 71.0],
        }
    ).to_parquet(parquet_dir / "wti_historico.parquet", index=False)
    return tmp_path


def test_load_data_cria_esquema_em_banco_vazio(repo_limpo: Path) -> None:
    load_data()

    with duckdb.connect(str(repo_limpo / "data" / "duckdb" / "inflatrack.duckdb")) as conexao:
        assert conexao.execute("SELECT count(*) FROM commodity_cotacao").fetchone()[0] == 2
        assert conexao.execute("SELECT count(*) FROM commodity").fetchone()[0] == 9
        assert conexao.execute("SELECT WTI FROM vw_features_daily").fetchall()


def test_load_data_e_idempotente(repo_limpo: Path) -> None:
    load_data()
    load_data()

    with duckdb.connect(str(repo_limpo / "data" / "duckdb" / "inflatrack.duckdb")) as conexao:
        assert conexao.execute("SELECT count(*) FROM commodity_cotacao").fetchone()[0] == 2
