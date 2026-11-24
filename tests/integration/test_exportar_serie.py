"""Gold (DuckDB) -> Postgres: a cópia que o Metabase lê. Precisa do Postgres no ar (`just up`).

Usa um schema temporário no Postgres, apagado no fim, para não tocar no `serie` de verdade.
Sem Postgres, os testes são pulados.
"""

import uuid
from pathlib import Path

import duckdb
import psycopg
import pytest

from inflatrack.common.db import dsn_do_ambiente
from inflatrack.reverse_etl import exportar_serie


@pytest.fixture
def dsn() -> str:
    dsn = dsn_do_ambiente()
    try:
        psycopg.connect(dsn, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("Postgres fora do ar")
    return dsn


@pytest.fixture
def schema(dsn: str):
    nome = f"teste_exportar_{uuid.uuid4().hex[:8]}"
    yield nome
    with psycopg.connect(dsn, autocommit=True) as pg:
        pg.execute(f"DROP SCHEMA IF EXISTS {nome} CASCADE")


@pytest.fixture
def gold(tmp_path: Path) -> Path:
    caminho = tmp_path / "analitico.duckdb"
    with duckdb.connect(str(caminho)) as conexao:
        conexao.execute("CREATE SCHEMA gold")
        conexao.execute(
            "CREATE TABLE gold.fato AS SELECT * FROM (VALUES "
            "(DATE '2026-08-01', 'A', 1.5::DECIMAL(12,4)), "
            "(DATE '2026-09-01', 'B', 2.25::DECIMAL(12,4))) t(mes_referencia, codigo, valor)"
        )
    return caminho


def _consultar(dsn: str, sql: str):
    with psycopg.connect(dsn) as pg:
        return pg.execute(sql).fetchall()


def test_primeira_copia_cria_a_tabela_com_os_tipos_da_gold(dsn, schema, gold) -> None:
    with exportar_serie.conectar(gold, dsn) as conexao:
        copiadas = exportar_serie.exportar(conexao, ("fato",), schema)

    assert copiadas == {"fato": 2}
    tipos = dict(
        _consultar(
            dsn,
            "select column_name, data_type from information_schema.columns "
            f"where table_schema = '{schema}' and table_name = 'fato'",
        )
    )
    assert tipos == {"mes_referencia": "date", "codigo": "character varying", "valor": "numeric"}


def test_copiar_de_novo_nao_duplica_e_mantem_o_indice(dsn, schema, gold) -> None:
    with exportar_serie.conectar(gold, dsn) as conexao:
        exportar_serie.exportar(conexao, ("fato",), schema)
    with psycopg.connect(dsn, autocommit=True) as pg:
        pg.execute(f"CREATE INDEX ix_fato_mes ON {schema}.fato (mes_referencia)")
    with duckdb.connect(str(gold)) as conexao:
        conexao.execute("UPDATE gold.fato SET valor = 9 WHERE codigo = 'B'")

    with exportar_serie.conectar(gold, dsn) as conexao:
        exportar_serie.exportar(conexao, ("fato",), schema)

    linhas = _consultar(dsn, f"select codigo, valor from {schema}.fato order by codigo")
    indices = _consultar(dsn, f"select indexname from pg_indexes where schemaname = '{schema}'")
    assert [(codigo, float(valor)) for codigo, valor in linhas] == [("A", 1.5), ("B", 9.0)]
    assert indices == [("ix_fato_mes",)]


def _persistencia(dsn: str, schema: str, tabela: str) -> str:
    return _consultar(
        dsn, f"select relpersistence from pg_class where oid = '{schema}.{tabela}'::regclass"
    )[0][0]


def _wal_atual(dsn: str) -> str:
    return _consultar(dsn, "select pg_current_wal_lsn()::text")[0][0]


def test_copia_cria_a_tabela_unlogged(dsn, schema, gold) -> None:
    """`serie` é cópia da Gold: sem WAL, a cópia não enche o slot do CDC (perdido em 2026-11-11)."""
    with exportar_serie.conectar(gold, dsn) as conexao:
        exportar_serie.exportar(conexao, ("fato",), schema)

    assert _persistencia(dsn, schema, "fato") == "u"


def test_tabela_comum_da_migration_vira_unlogged_e_mantem_indice_e_dados(dsn, schema, gold) -> None:
    with psycopg.connect(dsn, autocommit=True) as pg:
        pg.execute(f"CREATE SCHEMA {schema}")
        pg.execute(
            f"CREATE TABLE {schema}.fato (mes_referencia date, codigo varchar, valor numeric)"
        )
        pg.execute(f"CREATE INDEX ix_fato_codigo ON {schema}.fato (codigo)")

    with exportar_serie.conectar(gold, dsn) as conexao:
        exportar_serie.exportar(conexao, ("fato",), schema)

    assert _persistencia(dsn, schema, "fato") == "u"
    assert _consultar(dsn, f"select count(*) from {schema}.fato") == [(2,)]
    assert _consultar(dsn, f"select indexname from pg_indexes where schemaname = '{schema}'") == [
        ("ix_fato_codigo",)
    ]


def test_copia_numa_tabela_unlogged_quase_nao_gera_wal(dsn, schema, gold) -> None:
    with duckdb.connect(str(gold)) as conexao:
        conexao.execute(
            "INSERT INTO gold.fato SELECT DATE '2026-01-01', 'X' || g, g FROM range(50000) t(g)"
        )
    with exportar_serie.conectar(gold, dsn) as conexao:
        exportar_serie.exportar(conexao, ("fato",), schema)

    antes = _wal_atual(dsn)
    with exportar_serie.conectar(gold, dsn) as conexao:
        exportar_serie.exportar(conexao, ("fato",), schema)
    gerado = _consultar(dsn, f"select pg_wal_lsn_diff(pg_current_wal_lsn(), '{antes}')")[0][0]

    # Apagar e inserir 50 mil linhas numa tabela comum passa de 5 MB de WAL.
    assert gerado < 1_000_000


def test_estrutura_diferente_falha_sem_alterar_o_que_ja_estava_la(dsn, schema, gold) -> None:
    with exportar_serie.conectar(gold, dsn) as conexao:
        exportar_serie.exportar(conexao, ("fato",), schema)
    with duckdb.connect(str(gold)) as conexao:
        conexao.execute("ALTER TABLE gold.fato ADD COLUMN nova INTEGER")
        conexao.execute("DELETE FROM gold.fato")

    with (
        exportar_serie.conectar(gold, dsn) as conexao,
        pytest.raises(ValueError, match="colunas diferentes"),
    ):
        exportar_serie.exportar(conexao, ("fato",), schema)

    assert _consultar(dsn, f"select count(*) from {schema}.fato") == [(2,)]


def test_tabela_que_nao_existe_na_gold_falha_antes_de_escrever(dsn, schema, gold) -> None:
    with (
        exportar_serie.conectar(gold, dsn) as conexao,
        pytest.raises(ValueError, match="rode o dbt"),
    ):
        exportar_serie.exportar(conexao, ("nao_existe",), schema)

    assert _consultar(
        dsn, f"select count(*) from information_schema.schemata where schema_name = '{schema}'"
    ) == [(0,)]
