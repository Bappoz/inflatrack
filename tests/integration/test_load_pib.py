"""Carga da Bronze do PIB: Delta → ``bronze.pib_valor`` no DuckDB (respostas reais do SIDRA)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from inflatrack import bronze, bronze_pib
from inflatrack.loaders.load_pib import carregar, main

FIXTURES = Path(__file__).parent.parent / "fixtures" / "pib"
AGORA = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


@pytest.fixture
def nomes() -> dict[str, str]:
    metadados = json.loads((FIXTURES / "1846-metadados.json").read_text(encoding="utf-8"))
    return bronze_pib.nomes_dos_setores(metadados)


@pytest.fixture
def corpo_2026() -> str:
    return (FIXTURES / "1846-2026.json").read_text(encoding="utf-8")


def _gravar(destino: Path, corpo: str, nomes: dict[str, str]) -> None:
    resposta = bronze.Resposta(bronze_pib.requisicao_do_ano(2026), 200, "application/json", corpo)
    bronze_pib.gravar_anos(destino, [(2026, resposta)], nomes, AGORA)


def _total(conexao: duckdb.DuckDBPyConnection) -> int:
    return conexao.execute("SELECT count(*) FROM bronze.pib_valor").fetchone()[0]


def test_banco_vazio_cria_schema_e_tabela_com_tipos_do_delta(tmp_path, nomes, corpo_2026) -> None:
    _gravar(tmp_path / "pib", corpo_2026, nomes)

    with duckdb.connect(str(tmp_path / "t.duckdb")) as conexao:
        novas = carregar(conexao, tmp_path / "pib")
        tipos = dict(
            conexao.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'bronze' AND table_name = 'pib_valor'"
            ).fetchall()
        )

    assert novas == 46  # 2026: dois trimestres x 23 setores
    assert tipos["valor"] == "DECIMAL(20,4)"
    assert tipos["codigo_setor"] == "VARCHAR"


def test_dupla_carga_nao_duplica(tmp_path, nomes, corpo_2026) -> None:
    _gravar(tmp_path / "pib", corpo_2026, nomes)

    with duckdb.connect(str(tmp_path / "t.duckdb")) as conexao:
        primeira = carregar(conexao, tmp_path / "pib")
        segunda = carregar(conexao, tmp_path / "pib")
        total = _total(conexao)

    assert (primeira, segunda, total) == (46, 0, 46)


def test_revisao_do_ibge_entra_como_linha_nova_sem_apagar_a_anterior(
    tmp_path, nomes, corpo_2026
) -> None:
    _gravar(tmp_path / "pib", corpo_2026, nomes)
    with duckdb.connect(str(tmp_path / "t.duckdb")) as conexao:
        carregar(conexao, tmp_path / "pib")

    payload = json.loads(corpo_2026)
    original = payload[0]["V"]
    payload[0]["V"] = str(int(original) + 1)
    _gravar(tmp_path / "pib", json.dumps(payload), nomes)

    with duckdb.connect(str(tmp_path / "t.duckdb")) as conexao:
        novas = carregar(conexao, tmp_path / "pib")
        versoes = conexao.execute(
            "SELECT valor_bruto FROM bronze.pib_valor "
            "WHERE codigo_setor = ? AND data_referencia = ? ORDER BY valor_bruto",
            [payload[0]["D4C"], bronze_pib.transformar(payload, nomes)[0]["data_referencia"]],
        ).fetchall()

    assert novas == 1
    assert sorted(v for (v,) in versoes) == sorted([original, payload[0]["V"]])


def test_delta_inexistente_falha(tmp_path: Path) -> None:
    with (
        duckdb.connect(str(tmp_path / "t.duckdb")) as conexao,
        pytest.raises(FileNotFoundError, match="PIB"),
    ):
        carregar(conexao, tmp_path / "nao_existe")


def test_main_sem_delta_devolve_erro(tmp_path: Path) -> None:
    assert main(["--db", str(tmp_path / "t.duckdb"), "--delta-dir", str(tmp_path / "x")]) == 1
