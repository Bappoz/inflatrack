"""Testes de integração do loader de Dólar: Delta Lake → ``bronze.dolar_boletim`` no DuckDB."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from inflatrack.bronze import dolar
from inflatrack.loaders.load_dolar import carregar_bronze, main

FIXTURE_DOLAR = Path(__file__).parent.parent / "fixtures" / "dolar" / "olinda_amostra.json"


@pytest.fixture
def delta_dolar(tmp_path: Path) -> Path:
    """Prepara uma tabela Delta temporária com a fixture do Dólar."""
    corpo = FIXTURE_DOLAR.read_text(encoding="utf-8")
    destino = tmp_path / "dolar"
    dolar.gravar(destino, requisicao="teste:dolar", corpo=corpo)
    return destino


def test_banco_vazio_cria_schema_e_tabela_com_tipos_do_delta(
    tmp_path: Path, delta_dolar: Path
) -> None:
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as con:
        novas = carregar_bronze(con, delta_dolar, modo="acrescenta")
        assert novas == 4

        # Verificar tipos e schema
        colunas = dict(
            con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'bronze' AND table_name = 'dolar_boletim'"
            ).fetchall()
        )
        assert "data_hora_cotacao" in colunas
        assert "cotacao_compra" in colunas
        assert "cotacao_venda" in colunas
        assert "tipo_boletim" in colunas
        assert "ano" in colunas


def test_dupla_carga_nao_duplica(tmp_path: Path, delta_dolar: Path) -> None:
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as con:
        primeira = carregar_bronze(con, delta_dolar, modo="acrescenta")
        segunda = carregar_bronze(con, delta_dolar, modo="acrescenta")
        total = con.execute("SELECT count(*) FROM bronze.dolar_boletim").fetchone()[0]

        assert primeira == 4
        assert segunda == 0
        assert total == 4


def test_modo_substitui(tmp_path: Path, delta_dolar: Path) -> None:
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as con:
        primeira = carregar_bronze(con, delta_dolar, modo="substitui")
        segunda = carregar_bronze(con, delta_dolar, modo="substitui")
        total = con.execute("SELECT count(*) FROM bronze.dolar_boletim").fetchone()[0]

        assert primeira == 4
        assert segunda == 4
        assert total == 4


def test_tabela_delta_inexistente_levanta_erro(tmp_path: Path) -> None:
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as con, pytest.raises(FileNotFoundError):
        carregar_bronze(con, tmp_path / "pasta_vazia")


def test_modo_invalido_levanta_value_error(tmp_path: Path, delta_dolar: Path) -> None:
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as con, pytest.raises(ValueError, match="modo inválido"):
        carregar_bronze(con, delta_dolar, modo="invalido")


def test_main_cli(tmp_path: Path, delta_dolar: Path) -> None:
    db_path = tmp_path / "cli.duckdb"
    cod = main(["--db", str(db_path), "--delta-dir", str(delta_dolar)])
    assert cod == 0
    with duckdb.connect(str(db_path)) as con:
        total = con.execute("SELECT count(*) FROM bronze.dolar_boletim").fetchone()[0]
        assert total == 4
