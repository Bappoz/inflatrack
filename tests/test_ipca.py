"""Bronze do IPCA: transformação, checagens, idempotência e importação do Raw.

As fixtures de ``tests/fixtures/ipca/`` são respostas reais do SIDRA, baixadas em
2026-10-11 e gravadas byte a byte:

* ``7060-202001-recorte.json``: Brasil, São Paulo e Rio Branco x 4 variáveis x 3
  categorias (36 linhas). Recorte escolhido por ter, na mesma resposta, os marcadores
  ``...`` e ``-`` e valores negativos de verdade.
* ``1737-197912.json`` e ``1737-202609.json``: meses completos do número-índice (6 linhas).
"""

import gzip
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from deltalake import DeltaTable

from inflatrack import bronze_ipca, sidra

FIXTURES = Path(__file__).parent / "fixtures" / "ipca"
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


def test_transformar_mantem_todas_as_linhas(recorte) -> None:
    """O ingestor antigo descartava ~30% das linhas; a Bronze não descarta nenhuma."""
    linhas = bronze_ipca.transformar(recorte, 7060)

    assert len(linhas) == len(recorte) == 36
    assert [linha["valor_bruto"] for linha in linhas] == [objeto["V"] for objeto in recorte]


def test_transformar_marcador_vira_valor_nulo_com_o_texto_original(recorte) -> None:
    linhas = bronze_ipca.transformar(recorte, 7060)

    sem_valor = [linha for linha in linhas if linha["valor"] is None]
    assert {linha["valor_bruto"] for linha in sem_valor} == {"...", "-"}
    assert len(sem_valor) == 21


def test_transformar_nao_confunde_deflacao_com_marcador(recorte) -> None:
    """``-`` sozinho é ausente; ``-2.68`` é queda de preço e precisa sobreviver."""
    linhas = bronze_ipca.transformar(recorte, 7060)

    negativos = {
        linha["valor"] for linha in linhas if linha["valor"] is not None and linha["valor"] < 0
    }
    assert negativos == {Decimal("-2.68"), Decimal("-0.21")}


def test_transformar_converte_tipos_sem_inventar_padrao(recorte) -> None:
    primeira = bronze_ipca.transformar(recorte, 7060)[0]

    assert primeira == {
        "agregado": 7060,
        "mes_referencia": date(2020, 1, 1),
        "nivel_territorial": 1,
        "codigo_localidade": 1,
        "codigo_variavel": 63,
        "id_categoria": 7169,
        "codigo_unidade": 2,
        "valor": Decimal("0.21"),
        "valor_bruto": "0.21",
    }


def test_transformar_unidade_vazia_fica_nula(recorte) -> None:
    """Nas linhas ``...`` a API manda a unidade vazia; não se assume ``%``."""
    linhas = bronze_ipca.transformar(recorte, 7060)

    assert {linha["codigo_unidade"] for linha in linhas if linha["valor_bruto"] == "..."} == {None}


@pytest.mark.parametrize("marcador", sorted(sidra.MARCADORES_AUSENTE))
def test_transformar_reconhece_os_quatro_marcadores(recorte, marcador) -> None:
    """``..`` e ``X`` estão na ajuda da API, mas não apareceram nas respostas baixadas:
    este caso troca o valor de uma linha real à mão."""
    objeto = recorte[0] | {"V": marcador}

    (linha,) = bronze_ipca.transformar([objeto], 7060)

    assert linha["valor"] is None
    assert linha["valor_bruto"] == marcador


def test_transformar_1737_nao_tem_categoria() -> None:
    linhas = bronze_ipca.transformar(json.loads(corpo("1737-197912.json")), 1737)

    assert {linha["id_categoria"] for linha in linhas} == {None}
    # 13 casas decimais: em float o número-índice de 1979 perderia precisão.
    assert Decimal("0.0000000076183") in {linha["valor"] for linha in linhas}


def test_transformar_recusa_campo_inesperado(recorte) -> None:
    """Campo novo na API não pode sumir em silêncio: a extração para e avisa."""
    with pytest.raises(bronze_ipca.ChecagemError, match="campos"):
        bronze_ipca.transformar([recorte[0] | {"D5C": "1"}], 7060)


def test_transformar_recusa_valor_que_nao_e_numero_nem_marcador(recorte) -> None:
    with pytest.raises(bronze_ipca.ChecagemError, match="marcador"):
        bronze_ipca.transformar([recorte[0] | {"V": "n/d"}], 7060)


def test_checar_aceita_mes_completo() -> None:
    linhas = bronze_ipca.transformar(json.loads(corpo("1737-202609.json")), 1737)

    bronze_ipca.checar(linhas, 1737, "202609")


def test_checar_recusa_resposta_vazia() -> None:
    with pytest.raises(bronze_ipca.ChecagemError, match="vazia"):
        bronze_ipca.checar([], 7060)


def test_checar_recusa_mes_diferente_do_pedido() -> None:
    linhas = bronze_ipca.transformar(json.loads(corpo("1737-202609.json")), 1737)

    with pytest.raises(bronze_ipca.ChecagemError, match="pedido 202608"):
        bronze_ipca.checar(linhas, 1737, "202608")


def test_checar_recusa_volume_fora_da_referencia(recorte) -> None:
    """O recorte tem 3 localidades e 3 categorias; o 7060 completo tem 17 e 457."""
    linhas = bronze_ipca.transformar(recorte, 7060)

    with pytest.raises(bronze_ipca.ChecagemError, match="3 localidades .esperado 17."):
        bronze_ipca.checar(linhas, 7060)


def test_checar_recusa_buraco_no_retangulo(recorte, monkeypatch) -> None:
    referencia = bronze_ipca.Referencia(3, frozenset({63, 66, 69, 2265}), 3)
    monkeypatch.setitem(bronze_ipca.REFERENCIA, 7060, referencia)
    linhas = bronze_ipca.transformar(recorte, 7060)
    bronze_ipca.checar(linhas, 7060)  # o recorte inteiro passa

    with pytest.raises(bronze_ipca.ChecagemError, match="35 combinações de 36"):
        bronze_ipca.checar(linhas[:-1], 7060)


def test_gravar_preenche_as_duas_tabelas_com_linhagem(tmp_path) -> None:
    resposta = resposta_1737()

    gravacao = bronze_ipca.gravar(tmp_path, 1737, "202609", resposta, QUANDO)

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
    bronze_ipca.gravar(tmp_path, 1737, "202609", resposta_1737(), QUANDO)

    segunda = bronze_ipca.gravar(tmp_path, 1737, "202609", resposta_1737())

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
    bronze_ipca.gravar(tmp_path, 1737, "202609", resposta_1737(), QUANDO)
    # Simula o IBGE republicando só a variação mensal (variável 63): 0.82 -> 0.84.
    revisada = resposta_1737(texto=_editado("1737-202609.json", V="0.84"))

    gravacao = bronze_ipca.gravar(tmp_path, 1737, "202609", revisada)

    assert (gravacao.resposta_nova, gravacao.linhas_novas) == (True, 1)
    assert len(tabela(tmp_path, "resposta")) == 2
    mensal = [linha for linha in tabela(tmp_path, "observacao") if linha["codigo_variavel"] == 63]
    assert sorted(linha["valor_bruto"] for linha in mensal) == ["0.82", "0.84"]
    assert len({linha["_id_resposta"] for linha in mensal}) == 2


def test_resposta_reprovada_nao_e_gravada(tmp_path, recorte) -> None:
    """Promoção à Bronze: a checagem roda antes de qualquer escrita."""
    url = sidra.url_valores(7060, "202001")
    resposta = sidra.Resposta(url, 200, "application/json", corpo("7060-202001-recorte.json"))

    with pytest.raises(bronze_ipca.ChecagemError):
        bronze_ipca.gravar(tmp_path, 7060, "202001", resposta)

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

    respostas, observacoes, falhas = bronze_ipca.importar_raw(raw, bronze)

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
    bronze_ipca.importar_raw(raw, bronze)

    assert bronze_ipca.importar_raw(raw, bronze) == (0, 0, [])


def test_importar_raw_guarda_o_corpo_mesmo_quando_recusa_a_extracao(tmp_path) -> None:
    raw, bronze = tmp_path / "raw", tmp_path / "bronze"
    _raw_antigo(raw, "7060-202001-recorte.json").rename(raw / "7060-202001.json.gz")

    respostas, observacoes, falhas = bronze_ipca.importar_raw(raw, bronze)

    assert (respostas, observacoes) == (1, 0)
    assert len(falhas) == 1 and falhas[0].startswith("7060-202001.json.gz")
    assert len(tabela(bronze, "resposta")) == 1


def test_resumo_da_bronze_aponta_mes_faltando(tmp_path) -> None:
    bronze_ipca.gravar(tmp_path, 1737, "202609", resposta_1737(), QUANDO)
    julho = resposta_1737("202607", _editado("1737-202609.json", D3C="202607"))
    bronze_ipca.gravar(tmp_path, 1737, "202607", julho, QUANDO)

    (resumo,) = bronze_ipca.resumo_da_bronze(tmp_path)

    assert (resumo["meses"], resumo["meses_faltando"]) == (2, 1)
    assert (resumo["linhas"], resumo["meses_fora_do_volume"]) == (12, 0)
    assert resumo["linhas_de_revisao"] == 0
