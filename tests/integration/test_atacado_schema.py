"""Schema `atacado` (migration 0007): preços de atacadista só no Postgres. Precisa de `just up`.

Tudo roda numa transação desfeita no fim. Sem Postgres, ou sem a migration 0007, os testes são
pulados.
"""

import psycopg
import pytest

from inflatrack.common.db import dsn_do_ambiente

SUBITEM = "9999999"


@pytest.fixture
def pg():
    try:
        conexao = psycopg.connect(dsn_do_ambiente(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres fora do ar")
    with conexao:
        if conexao.execute("select to_regclass('atacado.preco')").fetchone()[0] is None:
            pytest.skip("banco sem a migration 0007")
        conexao.execute(
            "insert into classificacao (codigo, nivel) values (%s, 'subitem')"
            " on conflict (codigo) do nothing",
            (SUBITEM,),
        )
        yield conexao
        conexao.rollback()


def _produto(pg) -> int:
    (id_fornecedor,) = pg.execute(
        "insert into atacado.fornecedor (nome, codigo_localidade, ficticio)"
        " values ('Teste', 5300108, true) returning id"
    ).fetchone()
    (id_produto,) = pg.execute(
        "insert into atacado.produto (id_fornecedor, nome, unidade, codigo_subitem_ipca)"
        " values (%s, 'Arroz', '5 kg', %s) returning id",
        (id_fornecedor, SUBITEM),
    ).fetchone()
    return id_produto


def _preco(pg, id_produto: int, centavos: int, data: str) -> None:
    pg.execute(
        "insert into atacado.preco (id_produto, preco_centavos, vigente_desde) values (%s, %s, %s)",
        (id_produto, centavos, data),
    )


def test_update_em_preco_e_barrado(pg) -> None:
    id_produto = _produto(pg)
    _preco(pg, id_produto, 1000, "2026-01-01")

    with pytest.raises(psycopg.errors.RestrictViolation):
        pg.execute(
            "update atacado.preco set preco_centavos = 1 where id_produto = %s", (id_produto,)
        )


def test_subitem_inexistente_e_recusado(pg) -> None:
    (id_fornecedor,) = pg.execute(
        "insert into atacado.fornecedor (nome, codigo_localidade)"
        " values ('X', 5300108) returning id"
    ).fetchone()

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        pg.execute(
            "insert into atacado.produto (id_fornecedor, nome, unidade, codigo_subitem_ipca)"
            " values (%s, 'Y', 'un', 'nao-existe')",
            (id_fornecedor,),
        )


def test_preco_atual_devolve_o_mais_recente(pg) -> None:
    id_produto = _produto(pg)
    _preco(pg, id_produto, 1100, "2026-02-01")
    _preco(pg, id_produto, 1000, "2026-01-01")

    (centavos,) = pg.execute(
        "select preco_centavos from atacado.preco_atual where id_produto = %s", (id_produto,)
    ).fetchone()
    assert centavos == 1100


def test_preco_futuro_ainda_nao_e_o_atual(pg) -> None:
    id_produto = _produto(pg)
    _preco(pg, id_produto, 1000, "2026-01-01")
    _preco(pg, id_produto, 9999, "2999-01-01")

    (centavos,) = pg.execute(
        "select preco_centavos from atacado.preco_atual where id_produto = %s", (id_produto,)
    ).fetchone()
    assert centavos == 1000


def test_atacado_fora_da_publicacao_do_cdc(pg) -> None:
    (total,) = pg.execute(
        "select count(*) from pg_publication_tables"
        " where pubname = 'inflatrack_cdc' and schemaname = 'atacado'"
    ).fetchone()
    assert total == 0


def test_preco_zero_e_recusado(pg) -> None:
    id_produto = _produto(pg)

    with pytest.raises(psycopg.errors.CheckViolation):
        _preco(pg, id_produto, 0, "2026-01-01")
