"""Helper comum da Bronze: tabela de respostas, dois modos no Delta e dois no DuckDB."""

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pytest

from inflatrack import bronze

AGORA = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
ESQUEMA = bronze.esquema_extraido(
    [pa.field("serie", pa.string(), nullable=False), pa.field("valor", pa.int64())]
)


def _resposta(corpo: str) -> bronze.Resposta:
    return bronze.Resposta("https://exemplo/x", 200, "application/json", corpo)


def _linhas(serie: str, valores: list[int]) -> list[dict]:
    return bronze.com_metadados(
        [{"serie": serie, "valor": valor} for valor in valores],
        id_resposta="h",
        fonte="teste",
        requisicao="https://exemplo/x",
        ingerido_em=AGORA,
    )


def test_resposta_igual_nao_e_gravada_de_novo(tmp_path: Path) -> None:
    primeiro = bronze.gravar_resposta(tmp_path, "teste", _resposta('{"a": 1}'), AGORA)
    repetido = bronze.gravar_resposta(tmp_path, "teste", _resposta('{"a": 1}'), AGORA)
    outro = bronze.gravar_resposta(tmp_path, "teste", _resposta('{"a": 2}'), AGORA)

    assert primeiro == (bronze.hash_do_corpo('{"a": 1}'), True)
    assert repetido == (primeiro[0], False)
    assert outro[1] is True
    tabela = bronze.ler(tmp_path, "resposta")
    assert tabela.num_rows == 2
    assert tabela.schema.equals(bronze.ESQUEMA_RESPOSTA)


def test_acrescentar_ignora_repetida_e_guarda_revisao(tmp_path: Path) -> None:
    chave = ("serie", "valor")
    assert bronze.acrescentar(tmp_path, "t", _linhas("a", [1, 2]), ESQUEMA, chave) == 2
    assert bronze.acrescentar(tmp_path, "t", _linhas("a", [1, 2]), ESQUEMA, chave) == 0
    assert bronze.acrescentar(tmp_path, "t", _linhas("a", [2, 3]), ESQUEMA, chave) == 1
    assert sorted(bronze.ler(tmp_path, "t").column("valor").to_pylist()) == [1, 2, 3]


def test_substituir_particao_troca_so_a_particao(tmp_path: Path) -> None:
    bronze.substituir_particao(tmp_path, "t", _linhas("a", [1, 2]), ESQUEMA, {"serie": "a"})
    bronze.substituir_particao(tmp_path, "t", _linhas("b", [9]), ESQUEMA, {"serie": "b"})
    bronze.substituir_particao(tmp_path, "t", _linhas("a", [5]), ESQUEMA, {"serie": "a"})

    linhas = sorted(
        (linha["serie"], linha["valor"]) for linha in bronze.ler(tmp_path, "t").to_pylist()
    )
    assert linhas == [("a", 5), ("b", 9)]
    assert bronze.versao(tmp_path, "t") == 2


def test_substituir_por_nada_falha(tmp_path: Path) -> None:
    with pytest.raises(bronze.ChecagemError):
        bronze.substituir_particao(tmp_path, "t", [], ESQUEMA, {"serie": "a"})


def test_carga_duckdb_nos_dois_modos() -> None:
    conexao = duckdb.connect()
    origem = pa.Table.from_pylist(_linhas("a", [1, 2]), ESQUEMA)

    assert bronze.carregar_duckdb(conexao, origem, "ac", "acrescenta", ["serie", "valor"]) == 2
    assert bronze.carregar_duckdb(conexao, origem, "ac", "acrescenta", ["serie", "valor"]) == 0

    bronze.carregar_duckdb(conexao, origem, "sub", "substitui", ["serie"])
    nova = pa.Table.from_pylist(_linhas("a", [7]), ESQUEMA)
    assert bronze.carregar_duckdb(conexao, nova, "sub", "substitui", ["serie"]) == 1
    assert conexao.execute("select valor from sub").fetchall() == [(7,)]


def test_duplicadas() -> None:
    tabela = pa.Table.from_pylist(_linhas("a", [1, 1, 2]), ESQUEMA)
    assert bronze.duplicadas(tabela, ["serie", "valor"]) == 1
    assert bronze.duplicadas(tabela, ["serie"]) == 2
