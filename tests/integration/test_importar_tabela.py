"""Importador da tabela de preços do atacadista contra o Postgres. Precisa de `just up` e da 0007.

Cada teste roda numa transação desfeita no fim.
"""

from datetime import date

import psycopg
import pytest

from inflatrack.atacado.importar_tabela import LinhaPreco, Resultado, SubitemAusente, importar
from inflatrack.common.db import dsn_do_ambiente

SUBITENS = ("9999991", "9999992")
FORNECEDOR = "Atacadista de Teste"


@pytest.fixture
def pg():
    try:
        conexao = psycopg.connect(dsn_do_ambiente(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres fora do ar")
    with conexao:
        if conexao.execute("select to_regclass('atacado.preco')").fetchone()[0] is None:
            pytest.skip("banco sem a migration 0007")
        for codigo in SUBITENS:
            conexao.execute(
                "insert into classificacao (codigo, nivel) values (%s, 'subitem')"
                " on conflict (codigo) do nothing",
                (codigo,),
            )
        yield conexao
        conexao.rollback()


def _linhas(preco_arroz: int = 2490, data: date = date(2026, 11, 1)) -> list[LinhaPreco]:
    return [
        LinhaPreco("Arroz", "5 kg", preco_arroz, SUBITENS[0], data),
        LinhaPreco("Feijão", "1 kg", 795, SUBITENS[1], data),
    ]


def _importar(pg, linhas):
    return importar(pg, linhas, fornecedor=FORNECEDOR, codigo_localidade=5300108, ficticio=True)


def _preco_atual(pg, produto: str) -> int:
    return pg.execute(
        "select pa.preco_centavos from atacado.preco_atual pa"
        " join atacado.fornecedor f on f.id = pa.id_fornecedor"
        " where f.nome = %s and pa.produto = %s",
        (FORNECEDOR, produto),
    ).fetchone()[0]


def test_primeira_importacao_grava_produtos_e_precos(pg) -> None:
    assert _importar(pg, _linhas()) == Resultado(produtos_novos=2, precos_novos=2)
    assert _preco_atual(pg, "Arroz") == 2490


def test_reimportar_o_mesmo_arquivo_nao_grava_nada(pg) -> None:
    _importar(pg, _linhas())

    assert _importar(pg, _linhas()) == Resultado(produtos_novos=0, precos_novos=0)


def test_preco_novo_em_data_nova_vira_o_atual(pg) -> None:
    _importar(pg, _linhas())

    resultado = _importar(pg, _linhas(preco_arroz=2690, data=date(2026, 12, 1)))

    assert resultado == Resultado(produtos_novos=0, precos_novos=1)
    assert _preco_atual(pg, "Arroz") == 2690


def test_preco_igual_em_data_nova_nao_gera_linha(pg) -> None:
    _importar(pg, _linhas())

    assert _importar(pg, _linhas(data=date(2026, 12, 1))).precos_novos == 0


def test_mudar_preco_na_mesma_data_e_recusado(pg) -> None:
    """A tabela é insert-only: corrigir um preço exige data nova, não reescrever o histórico."""
    _importar(pg, _linhas())

    with pytest.raises(ValueError, match="Arroz"):
        _importar(pg, _linhas(preco_arroz=2590))


def test_subitem_ausente_falha_antes_de_gravar(pg) -> None:
    linhas = [LinhaPreco("Arroz", "5 kg", 2490, "0000000", date(2026, 11, 1))]

    with pytest.raises(SubitemAusente, match="0000000"):
        _importar(pg, linhas)

    (total,) = pg.execute(
        "select count(*) from atacado.fornecedor where nome = %s", (FORNECEDOR,)
    ).fetchone()
    assert total == 0
