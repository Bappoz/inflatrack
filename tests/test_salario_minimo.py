"""Testes da camada Bronze em Delta para Salário Mínimo (DIEESE).

Cobre transformação fiel, checagens de continuidade e volume, idempotência
de gravação nas tabelas Delta e importação do Raw antigo.
"""

import gzip
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from deltalake import DeltaTable

from inflatrack import bronze_salario_minimo

FIXTURES = Path(__file__).parent / "fixtures" / "salario_minimo"
QUANDO = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
def html_real() -> str:
    caminho = FIXTURES / "salario_minimo.html"
    return caminho.read_text(encoding="utf-8")


def tabela(destino: Path, nome: str) -> list[dict]:
    return DeltaTable(str(destino / nome)).to_pyarrow_table().to_pylist()


def test_transformar_mantem_todas_as_linhas(html_real) -> None:
    """Extrai exatamente todas as 387 linhas da tabela histórica desde 1994-07."""
    linhas = bronze_salario_minimo.transformar(html_real)
    assert len(linhas) == 387
    assert linhas[0]["ano_mes"] == "1994-07"
    assert linhas[0]["data_referencia"] == date(1994, 7, 1)
    assert linhas[0]["salario_nominal"] == Decimal("64.79")
    assert linhas[0]["salario_necessario"] == Decimal("590.33")


def test_transformar_nao_contem_coluna_calculada(html_real) -> None:
    """A coluna multiplo_necessario_nominal é regra analítica e fica para o dbt."""
    linhas = bronze_salario_minimo.transformar(html_real)
    for linha in linhas:
        assert "multiplo_necessario_nominal" not in linha


def test_transformar_converte_tipos_exatos(html_real) -> None:
    """Valores monetários são convertidos para Decimal exato de 2 casas."""
    linhas = bronze_salario_minimo.transformar(html_real)
    linha_recente = [item for item in linhas if item["ano_mes"] == "2026-08"][0]
    assert linha_recente["ano"] == 2026
    assert linha_recente["mes"] == 8
    assert linha_recente["salario_nominal"] == Decimal("1621.00")
    assert linha_recente["salario_necessario"] == Decimal("7565.86")


def test_checar_valido(html_real) -> None:
    linhas = bronze_salario_minimo.transformar(html_real)
    # Não deve levantar exceção
    bronze_salario_minimo.checar(linhas)


def test_checar_rejeita_vazio() -> None:
    with pytest.raises(bronze_salario_minimo.ChecagemError, match="vazia"):
        bronze_salario_minimo.checar([])


def test_checar_rejeita_duplicados(html_real) -> None:
    linhas = bronze_salario_minimo.transformar(html_real)
    linhas_com_duplicata = linhas + [linhas[0]]
    with pytest.raises(bronze_salario_minimo.ChecagemError, match="duplicados"):
        bronze_salario_minimo.checar(linhas_com_duplicata)


def test_checar_rejeita_inicio_incorreto(html_real) -> None:
    linhas = bronze_salario_minimo.transformar(html_real)[1:]  # Começando em 1994-08
    with pytest.raises(bronze_salario_minimo.ChecagemError, match="iniciar em 1994-07"):
        bronze_salario_minimo.checar(linhas)


def test_checar_rejeita_buraco_na_serie(html_real) -> None:
    linhas = bronze_salario_minimo.transformar(html_real)
    # Remove um mês no meio da série
    linhas_com_buraco = [item for item in linhas if item["ano_mes"] != "2015-05"]
    with pytest.raises(bronze_salario_minimo.ChecagemError, match="Buraco na série"):
        bronze_salario_minimo.checar(linhas_com_buraco)


def test_gravar_idempotente(tmp_path: Path, html_real) -> None:
    destino = tmp_path / "salario_minimo"

    # Primeira execução: grava tudo
    grav1 = bronze_salario_minimo.gravar(destino, html_real, ingerido_em=QUANDO)
    assert grav1.resposta_nova is True
    assert grav1.linhas_novas == 387
    assert grav1.linhas_lidas == 387

    # Segunda execução (mesmo conteúdo): não grava resposta nem linhas
    grav2 = bronze_salario_minimo.gravar(destino, html_real, ingerido_em=QUANDO)
    assert grav2.resposta_nova is False
    assert grav2.linhas_novas == 0
    assert grav2.linhas_lidas == 387

    # Verifica linhas gravadas no Delta
    respostas = tabela(destino, "resposta")
    meses = tabela(destino, "mes")
    assert len(respostas) == 1
    assert len(meses) == 387
    assert respostas[0]["_fonte"] == "salario_minimo"
    assert meses[0]["_id_resposta"] == respostas[0]["id_resposta"]


def test_gravar_revisao_historica(tmp_path: Path, html_real) -> None:
    """Se o DIEESE revisar um mês, o novo valor entra como linha nova e a antiga permanece."""
    destino = tmp_path / "salario_minimo"
    bronze_salario_minimo.gravar(destino, html_real, ingerido_em=QUANDO)

    # Simula revisão do mês de setembro/2026
    html_revisado = html_real.replace("R$ 7.750,01", "R$ 7.799,99")
    quando_depois = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
    grav_rev = bronze_salario_minimo.gravar(destino, html_revisado, ingerido_em=quando_depois)

    assert grav_rev.resposta_nova is True
    assert grav_rev.linhas_novas == 1  # Somente a linha revisada entra!

    meses = tabela(destino, "mes")
    setembro = [item for item in meses if item["ano_mes"] == "2026-09"]
    assert len(setembro) == 2
    valores = {item["salario_necessario"] for item in setembro}
    assert valores == {Decimal("7750.01"), Decimal("7799.99")}


def test_importar_raw(tmp_path: Path, html_real) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    caminho_gz = raw_dir / "salario_minimo.html.gz"
    with gzip.open(caminho_gz, "wt", encoding="utf-8") as f:
        f.write(html_real)

    destino = tmp_path / "salario_minimo"
    respostas, novas, falhas = bronze_salario_minimo.importar_raw(raw_dir, destino)

    assert falhas == []
    assert respostas == 1
    assert novas == 387

    # Reimportar o mesmo arquivo não duplica
    respostas2, novas2, falhas2 = bronze_salario_minimo.importar_raw(raw_dir, destino)
    assert falhas2 == []
    assert respostas2 == 0
    assert novas2 == 0


def test_checar_tabela(tmp_path: Path, html_real) -> None:
    destino = tmp_path / "salario_minimo"
    bronze_salario_minimo.gravar(destino, html_real)
    info = bronze_salario_minimo.checar_tabela(destino)
    assert info["linhas"] == 387
    assert info["primeiro_mes"] == "1994-07-01"
    assert info["ultimo_mes"] == "2026-09-01"


def test_carregar_duckdb_modos(tmp_path: Path, html_real) -> None:
    destino = tmp_path / "salario_minimo"
    bronze_salario_minimo.gravar(destino, html_real)

    db_path = tmp_path / "teste.duckdb"

    # Modo 1: substitui
    total1 = bronze_salario_minimo.carregar_duckdb(destino, db_path, modo="substitui")
    assert total1 == 387

    # Reexecução no modo substitui mantém as 387 linhas
    total1_reexec = bronze_salario_minimo.carregar_duckdb(destino, db_path, modo="substitui")
    assert total1_reexec == 387

    # Modo 2: so_acrescenta (sem novas linhas, total permanece 387)
    total2 = bronze_salario_minimo.carregar_duckdb(destino, db_path, modo="so_acrescenta")
    assert total2 == 387
