"""Testes de integração do loader da Selic: Delta Lake → ``bronze.selic_taxa`` no DuckDB."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from inflatrack.bronze import selic
from inflatrack.loaders.load_selic import carregar_bronze, main

FIXTURE_SELIC = Path(__file__).parent.parent / "fixtures" / "selic" / "sgs_amostra.json"


@pytest.fixture
def delta_selic(tmp_path: Path) -> Path:
    """Prepara uma tabela Delta temporária com a fixture da Selic."""
    corpo = FIXTURE_SELIC.read_text(encoding="utf-8")
    destino = tmp_path / "selic"
    selic.gravar(destino, requisicao="teste:selic", corpo=corpo)
    return destino


def test_banco_vazio_cria_schema_e_tabela_com_tipos_do_delta(
    tmp_path: Path, delta_selic: Path
) -> None:
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as con:
        novas = carregar_bronze(con, delta_selic, modo="acrescenta")
        assert novas == 3

        colunas = dict(
            con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'bronze' AND table_name = 'selic_taxa'"
            ).fetchall()
        )
        assert "data_referencia" in colunas
        assert "taxa_dia_pct" in colunas
        assert "taxa_anualizada_pct" in colunas
        assert "ano" in colunas


def test_dupla_carga_nao_duplica(tmp_path: Path, delta_selic: Path) -> None:
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as con:
        primeira = carregar_bronze(con, delta_selic, modo="acrescenta")
        segunda = carregar_bronze(con, delta_selic, modo="acrescenta")
        total = con.execute("SELECT count(*) FROM bronze.selic_taxa").fetchone()[0]

        assert primeira == 3
        assert segunda == 0
        assert total == 3


def test_modo_substitui(tmp_path: Path, delta_selic: Path) -> None:
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as con:
        primeira = carregar_bronze(con, delta_selic, modo="substitui")
        segunda = carregar_bronze(con, delta_selic, modo="substitui")
        total = con.execute("SELECT count(*) FROM bronze.selic_taxa").fetchone()[0]

        assert primeira == 3
        assert segunda == 3
        assert total == 3


def test_tabela_delta_inexistente_levanta_erro(tmp_path: Path) -> None:
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as con, pytest.raises(FileNotFoundError):
        carregar_bronze(con, tmp_path / "pasta_vazia")


def test_modo_invalido_levanta_value_error(tmp_path: Path, delta_selic: Path) -> None:
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as con, pytest.raises(ValueError, match="modo inválido"):
        carregar_bronze(con, delta_selic, modo="invalido")


def test_main_cli(tmp_path: Path, delta_selic: Path) -> None:
    db_path = tmp_path / "cli.duckdb"
    cod = main(["--db", str(db_path), "--delta-dir", str(delta_selic)])
    assert cod == 0
    with duckdb.connect(str(db_path)) as con:
        total = con.execute("SELECT count(*) FROM bronze.selic_taxa").fetchone()[0]
        assert total == 3
