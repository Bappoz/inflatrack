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
