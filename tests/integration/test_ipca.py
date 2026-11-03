"""IPCA, Nível 2: gravação em Delta, idempotência, importação do Raw e carga no DuckDB.

Usa as respostas reais de ``tests/fixtures/ipca/`` (ver ``tests/unit/test_ipca.py``) e pastas
temporárias. Os testes de ``sincronizar_cesta`` precisam do Postgres no ar e são pulados sem ele.
"""

import gzip
import json
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import psycopg
import pytest
from deltalake import DeltaTable

from inflatrack import sidra
from inflatrack.bronze import ipca
from inflatrack.common.db import dsn_do_ambiente
from inflatrack.loaders import load_ipca

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ipca"
QUANDO = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def corpo(nome: str) -> str:
    return (FIXTURES / nome).read_text(encoding="utf-8")


def resposta_1737(periodo: str = "202609", texto: str | None = None) -> sidra.Resposta:
    url = sidra.url_valores(1737, periodo, niveis="n1/all", classificacao=None)
    return sidra.Resposta(
        url, 200, "application/json; charset=utf-8", texto or corpo(f"1737-{periodo}.json")
    )


def tabela(destino: Path, nome: str) -> list[dict]:
    return DeltaTable(str(destino / nome)).to_pyarrow_table().to_pylist()


@pytest.fixture
def recorte() -> list[dict]:
    return json.loads(corpo("7060-202001-recorte.json"))


def test_gravar_preenche_as_duas_tabelas_com_linhagem(tmp_path) -> None:
    resposta = resposta_1737()

    gravacao = ipca.gravar(tmp_path, 1737, "202609", resposta, QUANDO)

    (guardada,) = tabela(tmp_path, "resposta")
    assert guardada["corpo"] == resposta.corpo
    assert guardada["id_resposta"] == guardada["hash_corpo"] == gravacao.id_resposta
    assert guardada["tamanho_bytes"] == len(resposta.corpo.encode())
    assert (guardada["status_http"], guardada["_requisicao"]) == (200, resposta.url)

    observacoes = tabela(tmp_path, "observacao")
    assert (gravacao.linhas_lidas, gravacao.linhas_novas, len(observacoes)) == (6, 6, 6)
    assert {linha["_id_resposta"] for linha in observacoes} == {gravacao.id_resposta}
    assert {linha["_fonte"] for linha in observacoes} == {"ipca"}
    assert {linha["_ingerido_em"] for linha in observacoes} == {QUANDO}


def test_reexecutar_o_mesmo_mes_nao_acrescenta_nada(tmp_path) -> None:
    ipca.gravar(tmp_path, 1737, "202609", resposta_1737(), QUANDO)

    segunda = ipca.gravar(tmp_path, 1737, "202609", resposta_1737())

    assert (segunda.resposta_nova, segunda.linhas_novas) == (False, 0)
    assert len(tabela(tmp_path, "resposta")) == 1
    assert len(tabela(tmp_path, "observacao")) == 6


def _editado(nome: str, **troca: str) -> str:
    """Corpo de uma fixture com um campo trocado em todas as linhas ou só na variável 63."""
    payload = json.loads(corpo(nome))
    for objeto in payload:
        if "V" not in troca or objeto["D2C"] == "63":
            objeto.update(troca)
    return json.dumps(payload)


def test_revisao_do_ibge_entra_como_linha_nova_e_preserva_a_anterior(tmp_path) -> None:
    ipca.gravar(tmp_path, 1737, "202609", resposta_1737(), QUANDO)
    # Simula o IBGE republicando só a variação mensal (variável 63): 0.82 -> 0.84.
    revisada = resposta_1737(texto=_editado("1737-202609.json", V="0.84"))

    gravacao = ipca.gravar(tmp_path, 1737, "202609", revisada)

    assert (gravacao.resposta_nova, gravacao.linhas_novas) == (True, 1)
    assert len(tabela(tmp_path, "resposta")) == 2
    mensal = [linha for linha in tabela(tmp_path, "observacao") if linha["codigo_variavel"] == 63]
    assert sorted(linha["valor_bruto"] for linha in mensal) == ["0.82", "0.84"]
    assert len({linha["_id_resposta"] for linha in mensal}) == 2


def test_resposta_reprovada_nao_e_gravada(tmp_path, recorte) -> None:
    """Promoção à Bronze: a checagem roda antes de qualquer escrita."""
    url = sidra.url_valores(7060, "202001")
    resposta = sidra.Resposta(url, 200, "application/json", corpo("7060-202001-recorte.json"))

    with pytest.raises(ipca.ChecagemError):
        ipca.gravar(tmp_path, 7060, "202001", resposta)

    assert list(tmp_path.iterdir()) == []


def _raw_antigo(raw_dir: Path, nome_fixture: str) -> Path:
    """Grava a fixture como o ingestor antigo gravava: ``json.dump`` do payload, em gzip."""
    raw_dir.mkdir(exist_ok=True)
    caminho = raw_dir / (nome_fixture + ".gz")
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        json.dump(json.loads(corpo(nome_fixture)), arquivo, ensure_ascii=False)
    return caminho


def test_importar_raw_reconstroi_a_requisicao_pelo_nome_do_arquivo(tmp_path) -> None:
    raw, bronze = tmp_path / "raw", tmp_path / "bronze"
    _raw_antigo(raw, "1737-197912.json")
    _raw_antigo(raw, "1737-202609.json")

    respostas, observacoes, falhas = ipca.importar_raw(raw, bronze)

    assert (respostas, observacoes, falhas) == (2, 12, [])
    guardadas = sorted(tabela(bronze, "resposta"), key=lambda linha: linha["_requisicao"])
    assert [linha["_requisicao"] for linha in guardadas] == [
        "https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/all/p/197912/f/c/h/n",
        "https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/all/p/202609/f/c/h/n",
    ]
    # O que o Raw antigo não guardou fica nulo, em vez de ser inventado.
    assert {(linha["status_http"], linha["tipo_conteudo"]) for linha in guardadas} == {(None, None)}


def test_importar_raw_duas_vezes_nao_duplica(tmp_path) -> None:
    raw, bronze = tmp_path / "raw", tmp_path / "bronze"
    _raw_antigo(raw, "1737-202609.json")
    ipca.importar_raw(raw, bronze)

    assert ipca.importar_raw(raw, bronze) == (0, 0, [])


def test_importar_raw_guarda_o_corpo_mesmo_quando_recusa_a_extracao(tmp_path) -> None:
    raw, bronze = tmp_path / "raw", tmp_path / "bronze"
    _raw_antigo(raw, "7060-202001-recorte.json").rename(raw / "7060-202001.json.gz")

    respostas, observacoes, falhas = ipca.importar_raw(raw, bronze)

    assert (respostas, observacoes) == (1, 0)
    assert len(falhas) == 1 and falhas[0].startswith("7060-202001.json.gz")
    assert len(tabela(bronze, "resposta")) == 1


def test_resumo_da_bronze_aponta_mes_faltando(tmp_path) -> None:
    ipca.gravar(tmp_path, 1737, "202609", resposta_1737(), QUANDO)
    julho = resposta_1737("202607", _editado("1737-202609.json", D3C="202607"))
    ipca.gravar(tmp_path, 1737, "202607", julho, QUANDO)

    (resumo,) = ipca.resumo_da_bronze(tmp_path)

    assert (resumo["meses"], resumo["meses_faltando"]) == (2, 1)
    assert (resumo["linhas"], resumo["meses_fora_do_volume"]) == (12, 0)
    assert resumo["linhas_de_revisao"] == 0


# --- Metadados --------------------------------------------------------------------


def _metadados(nome_subitem: str = "Arroz") -> sidra.Resposta:
    categorias = [{"id": 7169, "nome": "Índice geral"}]
    categorias += [{"id": 8000 + i, "nome": f"1101{i:03d}.Subitem {i}"} for i in range(3, 458)]
    categorias.append({"id": 7173, "nome": f"1101002.{nome_subitem}"})
    corpo_json = json.dumps(
        {
            "periodicidade": {"inicio": 202001, "fim": 202609},
            "classificacoes": [{"id": 315, "categorias": categorias}],
        }
    )
    url = sidra.URL_METADADOS.format(agregado=7060)
    return sidra.Resposta(url, 200, "application/json", corpo_json)


def test_gravar_metadados_e_idempotente_e_guarda_a_resposta(tmp_path) -> None:
    primeira = ipca.gravar_metadados(tmp_path, 7060, _metadados(), QUANDO)
    segunda = ipca.gravar_metadados(tmp_path, 7060, _metadados())

    assert (primeira.linhas_novas, segunda.linhas_novas) == (457, 0)
    assert not segunda.resposta_nova
    assert len(tabela(tmp_path, "metadados")) == 457
    assert len(tabela(tmp_path, "resposta")) == 1


def test_renomear_subitem_entra_como_versao_nova_e_preserva_a_anterior(tmp_path) -> None:
    ipca.gravar_metadados(tmp_path, 7060, _metadados("Arroz"), QUANDO)

    gravacao = ipca.gravar_metadados(tmp_path, 7060, _metadados("Arroz polido"))

    nomes = {
        linha["nome"] for linha in tabela(tmp_path, "metadados") if linha["codigo"] == "1101002"
    }
    assert gravacao.linhas_novas == 1
    assert nomes == {"Arroz", "Arroz polido"}


# --- Delta -> DuckDB --------------------------------------------------------------


def test_load_ipca_duas_vezes_nao_duplica_e_a_revisao_entra(tmp_path) -> None:
    ipca.gravar(tmp_path, 1737, "202609", resposta_1737(), QUANDO)
    ipca.gravar_metadados(tmp_path, 7060, _metadados(), QUANDO)
    with duckdb.connect(str(tmp_path / "a.duckdb")) as conexao:
        primeira = load_ipca.carregar(conexao, tmp_path)
        segunda = load_ipca.carregar(conexao, tmp_path)

        revisada = ipca.gravar(
            tmp_path,
            1737,
            "202609",
            resposta_1737(texto=_editado("1737-202609.json", V="1.23")),
            QUANDO,
        )
        terceira = load_ipca.carregar(conexao, tmp_path)
        total = conexao.execute("SELECT count(*) FROM bronze.ipca_observacao").fetchone()[0]

    assert primeira == {"bronze.ipca_observacao": 6, "bronze.ipca_metadados": 457}
    assert segunda == {"bronze.ipca_observacao": 0, "bronze.ipca_metadados": 0}
    assert terceira["bronze.ipca_observacao"] == revisada.linhas_novas > 0
    assert total == 6 + revisada.linhas_novas


def test_load_ipca_sem_delta_avisa_em_vez_de_criar_tabela_vazia(tmp_path) -> None:
    with duckdb.connect() as conexao, pytest.raises(FileNotFoundError, match="observacao"):
        load_ipca.carregar(conexao, tmp_path)


# --- Postgres: histórico da cesta (SCD tipo 2) ------------------------------------


@pytest.fixture
def pg():
    try:
        conexao = psycopg.connect(dsn_do_ambiente(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres fora do ar")
    with conexao:
        yield conexao
        conexao.rollback()  # nada do teste fica no banco


def _cesta(nome: str, fim: int = 202609) -> dict:
    # Três dígitos não têm pai (`sidra.categorias`), então o teste não precisa semear a hierarquia.
    codigo = f"9{uuid.uuid4().int % 100:02d}"
    return {
        "periodicidade": {"inicio": 202001, "fim": fim},
        "classificacoes": [{"id": 315, "categorias": [{"id": 99, "nome": f"{codigo}.{nome}"}]}],
    }


def _versoes(pg, codigo: str) -> list[tuple]:
    return pg.execute(
        "select nome, vigencia_inicio, vigencia_fim from classificacao_versao"
        " where codigo = %s and id_fonte = 7060 order by vigencia_inicio",
        (codigo,),
    ).fetchall()


def test_cesta_reexecutada_com_o_mesmo_nome_nao_cria_versao(pg) -> None:
    metadados = _cesta("Leite pasteurizado")
    (codigo,) = ipca.sincronizar_cesta(pg, 7060, metadados).values()

    ipca.sincronizar_cesta(pg, 7060, metadados)

    assert _versoes(pg, codigo) == [("Leite pasteurizado", date(2020, 1, 1), None)]


def test_renomear_na_cesta_fecha_a_versao_e_preserva_o_nome_antigo(pg) -> None:
    metadados = _cesta("Leite pasteurizado", fim=202606)
    (codigo,) = ipca.sincronizar_cesta(pg, 7060, metadados).values()

    categorias = metadados["classificacoes"][0]["categorias"]
    categorias[0]["nome"] = f"{codigo}.Leite longa vida"
    metadados["periodicidade"]["fim"] = 202609
    ipca.sincronizar_cesta(pg, 7060, metadados)

    assert _versoes(pg, codigo) == [
        ("Leite pasteurizado", date(2020, 1, 1), date(2026, 8, 1)),
        ("Leite longa vida", date(2026, 9, 1), None),
    ]


def test_cesta_recusa_duas_versoes_abertas_para_o_mesmo_codigo(pg) -> None:
    (codigo,) = ipca.sincronizar_cesta(pg, 7060, _cesta("Arroz")).values()

    with pytest.raises(psycopg.errors.UniqueViolation):
        pg.execute(
            "insert into classificacao_versao (codigo, id_fonte, nome, vigencia_inicio)"
            " values (%s, 7060, 'Outro', '2026-01-01')",
            (codigo,),
        )
