"""Carga da Bronze das commodities: Delta → ``bronze.commodities_cotacao`` no DuckDB."""

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from inflatrack.alphavantage import AlphaVantageClient
from inflatrack.load_commodities import carregar_bronze, main

from inflatrack import bronze, ingest_commodities

FIXTURES = Path(__file__).parent.parent / "fixtures" / "commodities"
COLETA = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def volume_do_recorte(monkeypatch: pytest.MonkeyPatch) -> None:
    """Os recortes têm poucas linhas; o mínimo real é testado na evidência."""
    monkeypatch.setattr(ingest_commodities, "LINHAS_MINIMAS", dict.fromkeys(["WTI", "CORN"], 1))


def _resposta(symbol: str) -> bronze.Resposta:
    corpo = (FIXTURES / f"{symbol.lower()}-recorte.json").read_text(encoding="utf-8")
    intervalo = ingest_commodities.COMMODITY_CONFIGS[symbol]["interval"]
    return bronze.Resposta(
        AlphaVantageClient.url_publica(symbol, intervalo), 200, "application/json", corpo
    )


@pytest.fixture
def delta_com_dados(tmp_path: Path) -> Path:
    """Grava WTI e CORN no Delta e devolve o diretório da Bronze."""
    delta_dir = tmp_path / "bronze_commodities"
    for symbol in ("WTI", "CORN"):
        ingest_commodities.gravar(delta_dir, symbol, _resposta(symbol), COLETA)
    return delta_dir


def _linhas_no_delta(delta_dir: Path) -> int:
    return bronze.ler(delta_dir, "cotacao").num_rows


def test_banco_vazio_cria_schema_e_tabela_com_tipos_do_delta(
    tmp_path: Path, delta_com_dados: Path
) -> None:
    with duckdb.connect(str(tmp_path / "t.duckdb")) as conexao:
        total = carregar_bronze(conexao, delta_com_dados)
        tipos = dict(
            conexao.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'bronze' AND table_name = 'commodities_cotacao'"
            ).fetchall()
        )
        simbolos = conexao.execute(
            "SELECT DISTINCT symbol FROM bronze.commodities_cotacao ORDER BY 1"
        ).fetchall()
        fonte = conexao.execute("SELECT DISTINCT _fonte FROM bronze.commodities_cotacao").fetchall()

    assert total == _linhas_no_delta(delta_com_dados)
    assert simbolos == [("CORN",), ("WTI",)]
    assert fonte == [("commodities",)]
    assert tipos["preco"] == "DECIMAL(28,14)"
    assert tipos["data_referencia"] == "DATE"


@pytest.mark.parametrize("modo", ["substitui", "acrescenta"])
def test_dupla_carga_nao_duplica(tmp_path: Path, delta_com_dados: Path, modo: str) -> None:
    with duckdb.connect(str(tmp_path / "t.duckdb")) as conexao:
        primeira = carregar_bronze(conexao, delta_com_dados, modo=modo)
        segunda = carregar_bronze(conexao, delta_com_dados, modo=modo)
        repetidas = conexao.execute(
            "SELECT count(*) - count(DISTINCT (symbol, data_referencia)) "
            "FROM bronze.commodities_cotacao"
        ).fetchone()[0]

    assert primeira == segunda == _linhas_no_delta(delta_com_dados)
    assert repetidas == 0


def test_substitui_troca_o_valor_que_mudou_no_delta(tmp_path: Path, delta_com_dados: Path) -> None:
    """Se o Delta troca a partição de um symbol, o DuckDB passa a ter o valor novo, sem sobra."""
    with duckdb.connect(str(tmp_path / "t.duckdb")) as conexao:
        carregar_bronze(conexao, delta_com_dados)
        # Simula a sobra de uma carga antiga: preço que não existe mais no Delta.
        conexao.execute("UPDATE bronze.commodities_cotacao SET preco = -1 WHERE symbol = 'WTI'")
        carregar_bronze(conexao, delta_com_dados, modo="substitui")
        sobras = conexao.execute(
            "SELECT count(*) FROM bronze.commodities_cotacao WHERE preco = -1"
        ).fetchone()[0]

    assert sobras == 0


def test_delta_inexistente_falha(tmp_path: Path) -> None:
    with (
        duckdb.connect(str(tmp_path / "t.duckdb")) as conexao,
        pytest.raises(FileNotFoundError, match="cotações"),
    ):
        carregar_bronze(conexao, tmp_path / "nao_existe")


def test_modo_invalido_falha(tmp_path: Path, delta_com_dados: Path) -> None:
    with (
        duckdb.connect(str(tmp_path / "t.duckdb")) as conexao,
        pytest.raises(ValueError, match="Modo de carga"),
    ):
        carregar_bronze(conexao, delta_com_dados, modo="so_acrescenta")


def test_main_sem_delta_devolve_erro(tmp_path: Path) -> None:
    assert main(["--db", str(tmp_path / "t.duckdb"), "--delta-dir", str(tmp_path / "x")]) == 1
