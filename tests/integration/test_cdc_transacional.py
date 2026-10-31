"""CDC, Nível 2: mudanças reais no Postgres aparecem na Bronze. Precisa de `just up`.

Cada teste usa um slot próprio, apagado no fim. Sem Postgres, ou com um banco que ainda não
recebeu a migration 0004 e o wal_level=logical, os testes são pulados.
"""

import json
import uuid
from pathlib import Path

import duckdb
import psycopg
import pytest
from deltalake import DeltaTable

from inflatrack.cdc import simular_mudancas, transacional
from inflatrack.common.db import dsn_do_ambiente
from inflatrack.loaders import load_transacional

CHAVE = "chave-de-teste"


@pytest.fixture
def pg():
    try:
        conexao = psycopg.connect(dsn_do_ambiente(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres fora do ar")
    with conexao:
        (wal_level,) = conexao.execute("show wal_level").fetchone()
        publicacao = conexao.execute(
            "select 1 from pg_publication where pubname = %s", (transacional.PUBLICACAO,)
        ).fetchone()
        if wal_level != "logical" or publicacao is None:
            pytest.skip("banco sem wal_level=logical ou sem a migration 0004")
        yield conexao


@pytest.fixture
def slot(pg):
    nome = f"teste_{uuid.uuid4().hex[:10]}"
    yield nome
    pg.execute(
        "select pg_drop_replication_slot(slot_name) from pg_replication_slots where slot_name = %s",
        (nome,),
    )


@pytest.fixture
def cnpj(pg):
    """Um lojista próprio por teste: não interfere em outro dado do banco."""
    numero = f"{uuid.uuid4().int % 10**14:014d}"
    yield numero
    pg.execute("delete from lojista where cnpj = %s", (numero,))


def _lojista(pg, cnpj: str) -> int:
    pg.execute(
        "insert into classificacao (codigo, nivel) values ('1', 'grupo'), ('1101002', 'subitem')"
        " on conflict (codigo) do nothing"
    )
    return pg.execute(
        "insert into lojista (nome_fantasia, cnpj, codigo_localidade, codigo_grupo_ipca)"
        " values ('Loja de Teste', %s, 5300108, '1') returning id",
        (cnpj,),
    ).fetchone()[0]


def _produto(pg, id_lojista: int, nome: str = "Arroz") -> int:
    return pg.execute(
        "insert into produto (id_lojista, nome, preco_inicial_centavos, custo_inicial_centavos,"
        " codigo_subitem_ipca) values (%s, %s, 1000, 700, '1101002') returning id",
        (id_lojista, nome),
    ).fetchone()[0]


def _bronze(destino: Path) -> list[dict]:
    return DeltaTable(str(destino / "mudanca")).to_pyarrow_table().to_pylist()


def _capturar(pg, destino: Path, slot: str, **opcoes) -> transacional.Captura:
    return transacional.capturar(pg, destino, CHAVE, slot=slot, **opcoes)


def test_insert_update_e_delete_chegam_a_bronze_com_a_linha_anterior(pg, slot, cnpj, tmp_path):
    _capturar(pg, tmp_path, slot)
    id_produto = _produto(pg, _lojista(pg, cnpj))
    pg.execute("update produto set nome = 'Arroz 5kg' where id = %s", (id_produto,))
    pg.execute("delete from produto where id = %s", (id_produto,))

    _capturar(pg, tmp_path, slot)

    eventos = [
        linha
        for linha in _bronze(tmp_path)
        if linha["tabela"] == "produto" and linha["id_registro"] == id_produto
    ]
    assert [linha["operacao"] for linha in sorted(eventos, key=lambda x: x["lsn"])] == [
        "I",
        "U",
        "D",
    ]
    update = next(linha for linha in eventos if linha["operacao"] == "U")
    assert json.loads(update["antes"])["nome"] == "Arroz"
    assert json.loads(update["depois"])["nome"] == "Arroz 5kg"
    delete = next(linha for linha in eventos if linha["operacao"] == "D")
    assert json.loads(delete["antes"])["nome"] == "Arroz 5kg"


def test_primeira_captura_grava_a_foto_do_que_ja_existia(pg, slot, cnpj, tmp_path):
    id_lojista = _lojista(pg, cnpj)

    captura = _capturar(pg, tmp_path, slot)

    assert captura.foto
    foto = [
        linha
        for linha in _bronze(tmp_path)
        if linha["tabela"] == "lojista" and linha["id_registro"] == id_lojista
    ]
    assert [linha["operacao"] for linha in foto] == ["r"]


def test_cnpj_nunca_chega_a_bronze(pg, slot, cnpj, tmp_path):
    id_lojista = _lojista(pg, cnpj)  # entra pela foto
    _capturar(pg, tmp_path, slot)
    pg.execute("update lojista set nome_fantasia = 'Outro nome' where id = %s", (id_lojista,))
    pg.execute("delete from lojista where id = %s", (id_lojista,))  # e pelos eventos

    _capturar(pg, tmp_path, slot)

    linhas = _bronze(tmp_path)
    assert {"U", "D"} <= {linha["operacao"] for linha in linhas if linha["tabela"] == "lojista"}
    assert cnpj not in str(linhas)
    esperado = transacional.hash_estabelecimento(cnpj, CHAVE)
    assert all(
        json.loads(linha["antes"] or linha["depois"])["hash_estabelecimento"] == esperado
        for linha in linhas
        if linha["tabela"] == "lojista" and linha["id_registro"] == id_lojista
    )


def test_queda_antes_de_avancar_o_slot_nao_perde_nem_duplica(pg, slot, cnpj, tmp_path):
    id_lojista = _lojista(pg, cnpj)
    _capturar(pg, tmp_path, slot)
    _produto(pg, id_lojista)

    caiu = _capturar(pg, tmp_path, slot, avancar=False)
    retomada = _capturar(pg, tmp_path, slot)
    seguinte = _capturar(pg, tmp_path, slot)

    assert caiu.novas == 1
    assert (retomada.lidas, retomada.novas) == (1, 0)  # releu e não duplicou
    assert seguinte.lidas == 0  # o slot avançou de verdade


def test_mudanca_com_o_cdc_parado_e_lida_depois(pg, slot, cnpj, tmp_path):
    id_lojista = _lojista(pg, cnpj)
    _capturar(pg, tmp_path, slot)
    for indice in range(5):
        _produto(pg, id_lojista, f"Produto {indice}")

    assert _capturar(pg, tmp_path, slot).novas == 5


def test_escrita_fora_das_tabelas_publicadas_nao_gera_evento(pg, slot, tmp_path):
    """`serie` e a referência do IBGE ficam fora da publicação: sem laço de retroalimentação."""
    _capturar(pg, tmp_path, slot)
    pg.execute(
        "insert into classificacao (codigo, nivel) values ('9999999', 'subitem')"
        " on conflict (codigo) do nothing"
    )
    schema = f"teste_{uuid.uuid4().hex[:8]}"
    pg.execute(f"create schema {schema}")
    pg.execute(f"create table {schema}.fato as select 1 as id")
    pg.execute(f"drop schema {schema} cascade")
    pg.execute("delete from classificacao where codigo = '9999999'")

    assert _capturar(pg, tmp_path, slot).lidas == 0


def test_historico_nao_aceita_update(pg, cnpj):
    id_produto = _produto(pg, _lojista(pg, cnpj))
    pg.execute(
        "insert into reajuste (id_produto, preco_anterior_centavos, preco_novo_centavos, motivo)"
        " values (%s, 1000, 1100, 'teste')",
        (id_produto,),
    )

    with pytest.raises(psycopg.errors.RestrictViolation, match="insert-only"):
        pg.execute("update reajuste set motivo = 'x' where id_produto = %s", (id_produto,))


def test_simulacao_demonstra_reprocessamento_e_atraso_sem_vazar_cnpj(pg, slot, tmp_path):
    # O cenário usa e recria o próprio lojista; a demonstração falha sozinha se o CNPJ vazar.
    resultado = simular_mudancas.simular(pg, tmp_path, CHAVE, slot)

    assert resultado["antes_da_queda"].novas == resultado["antes_da_queda"].lidas > 0
    assert resultado["depois_da_queda"].novas == 0
    assert resultado["atrasado"].novas == 1
    pg.execute("delete from lojista where cnpj = %s", (simular_mudancas.CNPJ_FICTICIO,))


def test_load_transacional_duas_vezes_nao_duplica(pg, slot, cnpj, tmp_path):
    id_lojista = _lojista(pg, cnpj)
    _capturar(pg, tmp_path, slot)
    _produto(pg, id_lojista)
    _capturar(pg, tmp_path, slot)

    with duckdb.connect(str(tmp_path / "a.duckdb")) as conexao:
        primeira = load_transacional.carregar(conexao, tmp_path)
        segunda = load_transacional.carregar(conexao, tmp_path)
        total = conexao.execute(
            f"select count(*) from {load_transacional.TABELA_DUCKDB}"
        ).fetchone()

    assert primeira == total[0] == len(_bronze(tmp_path))
    assert segunda == 0


def test_load_transacional_sem_delta_cria_tabela_vazia(tmp_path):
    """Sem isso, `dbt build` de quem não roda o CDC quebraria nos modelos do lojista."""
    with duckdb.connect() as conexao:
        assert load_transacional.carregar(conexao, tmp_path) == 0
        colunas = [c[0] for c in conexao.execute("describe bronze.transacional_mudanca").fetchall()]

    assert colunas == transacional.ESQUEMA_MUDANCA.names
