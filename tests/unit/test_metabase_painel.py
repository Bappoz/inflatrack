"""Painel do Metabase versionado: leitura do painel.toml e conversa com a API (simulada)."""

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

_CAMINHO = Path(__file__).resolve().parents[2] / "scripts" / "metabase_painel.py"
_spec = importlib.util.spec_from_file_location("metabase_painel", _CAMINHO)
mp = importlib.util.module_from_spec(_spec)
sys.modules["metabase_painel"] = mp  # o @dataclass procura o módulo aqui
_spec.loader.exec_module(mp)


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Os padrões do script, sem depender do .env nem do ambiente de quem roda o teste."""
    for variavel in ("POSTGRES_DB", "POSTGRES_USER", "METABASE_PG_USER", "METABASE_PG_PASSWORD"):
        monkeypatch.delenv(variavel, raising=False)


def test_painel_do_repositorio_carrega_e_toda_pergunta_tem_sql() -> None:
    painel = mp.ler_painel()

    assert painel.perguntas, "painel.toml sem perguntas"
    for pergunta in painel.perguntas:
        assert pergunta.sql.strip(), pergunta.titulo
        assert pergunta.banco in painel.bancos
        assert pergunta.coluna >= 0 and pergunta.coluna + pergunta.largura <= 24


def test_banco_desconhecido_e_recusado(tmp_path: Path) -> None:
    (tmp_path / "x.sql").write_text("select 1", encoding="utf-8")
    (tmp_path / "painel.toml").write_text(
        '[painel]\nnome = "p"\ncolecao = "c"\n[bancos.postgres]\nnome = "pg"\nengine = "postgres"\n'
        '[[perguntas]]\narquivo = "x.sql"\ntitulo = "t"\nbanco = "oracle"\n'
        "posicao = { linha = 0, coluna = 0, largura = 4, altura = 4 }\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="oracle"):
        mp.ler_painel(tmp_path)


def test_conexao_com_o_duckdb_e_recusada() -> None:
    """Uma conexão do Metabase aberta no arquivo do DuckDB trava o dbt e os loaders."""
    with pytest.raises(ValueError, match="só o Postgres"):
        mp.detalhes_do_banco({"engine": "duckdb", "arquivo": "/duckdb/x.duckdb"})


def test_corpo_da_pergunta_e_sql_nativo_com_eixos() -> None:
    pergunta = mp.ler_painel().perguntas[0]
    corpo = mp.corpo_da_pergunta(pergunta, id_banco=7, id_colecao=3)

    assert corpo["dataset_query"] == {
        "type": "native",
        "database": 7,
        "native": {"query": pergunta.sql},
    }
    assert corpo["collection_id"] == 3
    assert corpo["visualization_settings"]["graph.dimensions"] == [pergunta.eixo_x]


def _metabase_falso(bancos: list[dict], atualizados: list | None = None):
    criados: list[dict] = []
    atualizados = atualizados if atualizados is not None else []

    def responder(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.method == "GET" and requisicao.url.path == "/api/database":
            return httpx.Response(200, json={"data": bancos})
        if requisicao.method == "POST" and requisicao.url.path == "/api/database":
            criados.append(json.loads(requisicao.content))
            return httpx.Response(200, json={"id": 99})
        if requisicao.method == "PUT" and requisicao.url.path.startswith("/api/database/"):
            atualizados.append((requisicao.url.path, json.loads(requisicao.content)))
            return httpx.Response(200, json={})
        return httpx.Response(404)

    cliente = httpx.Client(base_url="http://mb", transport=httpx.MockTransport(responder))
    return mp.Metabase("http://mb", cliente), criados


POSTGRES = {"nome": "InflaTrack — Postgres", "engine": "postgres"}


def test_reaproveita_conexao_criada_a_mao_com_outro_nome() -> None:
    feita_na_interface = {
        "id": 2,
        "name": "Inflatrack (Postgres)",
        "engine": "postgres",
        "details": {"host": "db", "dbname": "inflatrack", "port": 5432},
    }
    atualizados: list = []
    metabase, criados = _metabase_falso([feita_na_interface], atualizados)

    assert metabase.garantir_banco(POSTGRES) == 2
    assert criados == []
    # A conexão feita à mão (sem usuário ou com o dono do banco) passa a usar o leitor.
    assert atualizados[0][0] == "/api/database/2"
    assert atualizados[0][1]["details"]["user"] == "metabase_painel"


def test_conexao_que_ja_usa_o_leitor_nao_e_alterada() -> None:
    pronta = {
        "id": 5,
        "name": "InflaTrack — Postgres",
        "engine": "postgres",
        "details": {"host": "db", "dbname": "inflatrack", "user": "metabase_painel"},
    }
    atualizados: list = []
    metabase, _ = _metabase_falso([pronta], atualizados)

    assert metabase.garantir_banco(POSTGRES) == 5
    assert atualizados == []


def test_metabase_conecta_com_o_leitor_e_nunca_com_o_dono(monkeypatch) -> None:
    """Com o dono do banco, o painel leria `public` inteiro, inclusive os preços de cada loja."""
    monkeypatch.setenv("POSTGRES_USER", "inflatrack")
    detalhes = mp.detalhes_do_banco(POSTGRES)
    assert detalhes["user"] == "metabase_painel"
    assert detalhes["user"] != "inflatrack"


def test_toda_pergunta_le_so_a_vitrine_serie() -> None:
    """Seção 1.1: o Metabase lê só `serie`. Nada de `public`, DuckDB ou `int_*`."""
    import re

    for pergunta in mp.ler_painel().perguntas:
        sem_comentario = re.sub(r"--[^\n]*", "", pergunta.sql)
        # `extract(month from coluna)` não é leitura de tabela.
        sem_comentario = re.sub(r"extract\s*\([^)]*\)", "", sem_comentario, flags=re.IGNORECASE)
        ctes = set(re.findall(r"\b(\w+)\s+as\s*\(", sem_comentario, flags=re.IGNORECASE))
        lidas = re.findall(r"\b(?:from|join)\s+([\w.]+)", sem_comentario, flags=re.IGNORECASE)
        tabelas = [t for t in lidas if t not in ctes]
        assert tabelas, pergunta.titulo
        for tabela in tabelas:
            assert tabela.startswith("serie."), (pergunta.titulo, tabela)


def test_cria_a_conexao_quando_nao_existe() -> None:
    outro_banco = {"id": 1, "name": "Sample Database", "engine": "h2", "details": {}}
    metabase, criados = _metabase_falso([outro_banco])

    assert metabase.garantir_banco(POSTGRES) == 99
    assert criados[0]["engine"] == "postgres"
    assert criados[0]["details"]["host"] == "db"
