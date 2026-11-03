"""Vitrine `serie` (migration 0005): quem lê e quem escreve. Precisa de `just up`.

Tudo roda numa transação desfeita no fim, com ``SET LOCAL ROLE``: nada fica no banco. Sem Postgres,
ou com um banco que ainda não recebeu a migration 0005, os testes são pulados.
"""

import psycopg
import pytest

from inflatrack.common.db import dsn_do_ambiente
from inflatrack.reverse_etl import exportar_serie


@pytest.fixture
def pg():
    try:
        conexao = psycopg.connect(dsn_do_ambiente(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres fora do ar")
    with conexao:
        existe = conexao.execute("select to_regclass('serie.fct_inflacao_mensal')").fetchone()[0]
        if existe is None:
            pytest.skip("banco sem a migration 0005")
        yield conexao
        conexao.rollback()


INSERT_LOCALIDADE = (
    "insert into serie.dim_localidade (codigo_localidade, nome_localidade, tipo_localidade)"
    " values (-1, 'Teste', 'pais')"
)


def test_lojista_le_a_serie_oficial_mas_nao_escreve(pg) -> None:
    pg.execute("set local role lojista_app")

    pg.execute("select count(*) from serie.fct_inflacao_mensal")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        pg.execute(INSERT_LOCALIDADE)


@pytest.mark.parametrize("tabela", ["fct_reajuste_lojista", "dim_produto_preco_scd2"])
def test_lojista_nao_le_os_precos_de_outras_lojas(pg, tabela: str) -> None:
    """Sem RLS (E4), um GRANT nestas tabelas abriria os preços de uma loja para todas as outras."""
    pg.execute("set local role lojista_app")

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        pg.execute(f"select count(*) from serie.{tabela}")


def test_painel_le_tudo_e_nao_escreve(pg) -> None:
    pg.execute("set local role metabase_leitor")

    for tabela in exportar_serie.TABELAS:
        pg.execute(f"select count(*) from serie.{tabela}")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        pg.execute(INSERT_LOCALIDADE)


def test_so_o_pipeline_escreve_e_alcanca_todas_as_tabelas_copiadas(pg) -> None:
    pg.execute("set local role inflatrack_pipeline")

    pg.execute(INSERT_LOCALIDADE)
    for tabela in exportar_serie.TABELAS:
        pg.execute(f"delete from serie.{tabela} where false")


def test_todas_as_tabelas_copiadas_existem_na_migration(pg) -> None:
    existentes = {
        linha[0]
        for linha in pg.execute(
            "select table_name from information_schema.tables where table_schema = 'serie'"
        ).fetchall()
    }

    assert set(exportar_serie.TABELAS) <= existentes
