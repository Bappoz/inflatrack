"""IPCA, Nível 1: parsing e checagem das respostas do SIDRA, sem disco nem rede.

As fixtures de ``tests/fixtures/ipca/`` são respostas reais do SIDRA, baixadas em
2026-10-11 e gravadas byte a byte:

* ``7060-202001-recorte.json``: Brasil, São Paulo e Rio Branco x 4 variáveis x 3
  categorias (36 linhas). Recorte escolhido por ter, na mesma resposta, os marcadores
  ``...`` e ``-`` e valores negativos de verdade.
* ``1737-197912.json`` e ``1737-202609.json``: meses completos do número-índice (6 linhas).
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from inflatrack import sidra
from inflatrack.bronze import ipca

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ipca"


def corpo(nome: str) -> str:
    return (FIXTURES / nome).read_text(encoding="utf-8")


@pytest.fixture
def recorte() -> list[dict]:
    return json.loads(corpo("7060-202001-recorte.json"))


METADADOS = {
    "periodicidade": {"frequencia": "mensal", "inicio": 202001, "fim": 202609},
    "classificacoes": [
        {
            "id": 315,
            "categorias": [
                {"id": 7169, "nome": "Índice geral"},
                {"id": 7170, "nome": "1.Alimentação e bebidas"},
                {"id": 7172, "nome": "1101.Cereais"},
                {"id": 7173, "nome": "1101002.Arroz"},
            ],
        }
    ],
}


def test_transformar_mantem_todas_as_linhas(recorte) -> None:
    """O ingestor antigo descartava ~30% das linhas; a Bronze não descarta nenhuma."""
    linhas = ipca.transformar(recorte, 7060)

    assert len(linhas) == len(recorte) == 36
    assert [linha["valor_bruto"] for linha in linhas] == [objeto["V"] for objeto in recorte]


def test_transformar_marcador_vira_valor_nulo_com_o_texto_original(recorte) -> None:
    linhas = ipca.transformar(recorte, 7060)

    sem_valor = [linha for linha in linhas if linha["valor"] is None]
    assert {linha["valor_bruto"] for linha in sem_valor} == {"...", "-"}
    assert len(sem_valor) == 21


def test_transformar_nao_confunde_deflacao_com_marcador(recorte) -> None:
    """``-`` sozinho é ausente; ``-2.68`` é queda de preço e precisa sobreviver."""
    linhas = ipca.transformar(recorte, 7060)

    negativos = {
        linha["valor"] for linha in linhas if linha["valor"] is not None and linha["valor"] < 0
    }
    assert negativos == {Decimal("-2.68"), Decimal("-0.21")}


def test_transformar_converte_tipos_sem_inventar_padrao(recorte) -> None:
    primeira = ipca.transformar(recorte, 7060)[0]

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
    linhas = ipca.transformar(recorte, 7060)

    assert {linha["codigo_unidade"] for linha in linhas if linha["valor_bruto"] == "..."} == {None}


@pytest.mark.parametrize("marcador", sorted(sidra.MARCADORES_AUSENTE))
def test_transformar_reconhece_os_quatro_marcadores(recorte, marcador) -> None:
    """``..`` e ``X`` estão na ajuda da API, mas não apareceram nas respostas baixadas:
    este caso troca o valor de uma linha real à mão."""
    objeto = recorte[0] | {"V": marcador}

    (linha,) = ipca.transformar([objeto], 7060)

    assert linha["valor"] is None
    assert linha["valor_bruto"] == marcador


def test_transformar_1737_nao_tem_categoria() -> None:
    linhas = ipca.transformar(json.loads(corpo("1737-197912.json")), 1737)

    assert {linha["id_categoria"] for linha in linhas} == {None}
    # 13 casas decimais: em float o número-índice de 1979 perderia precisão.
    assert Decimal("0.0000000076183") in {linha["valor"] for linha in linhas}


def test_transformar_recusa_campo_inesperado(recorte) -> None:
    """Campo novo na API não pode sumir em silêncio: a extração para e avisa."""
    with pytest.raises(ipca.ChecagemError, match="campos"):
        ipca.transformar([recorte[0] | {"D5C": "1"}], 7060)


def test_transformar_recusa_valor_que_nao_e_numero_nem_marcador(recorte) -> None:
    with pytest.raises(ipca.ChecagemError, match="marcador"):
        ipca.transformar([recorte[0] | {"V": "n/d"}], 7060)


def test_checar_aceita_mes_completo() -> None:
    linhas = ipca.transformar(json.loads(corpo("1737-202609.json")), 1737)

    ipca.checar(linhas, 1737, "202609")


def test_checar_recusa_resposta_vazia() -> None:
    with pytest.raises(ipca.ChecagemError, match="vazia"):
        ipca.checar([], 7060)


def test_checar_recusa_mes_diferente_do_pedido() -> None:
    linhas = ipca.transformar(json.loads(corpo("1737-202609.json")), 1737)

    with pytest.raises(ipca.ChecagemError, match="pedido 202608"):
        ipca.checar(linhas, 1737, "202608")


def test_checar_recusa_volume_fora_da_referencia(recorte) -> None:
    """O recorte tem 3 localidades e 3 categorias; o 7060 completo tem 17 e 457."""
    linhas = ipca.transformar(recorte, 7060)

    with pytest.raises(ipca.ChecagemError, match="3 localidades .esperado 17."):
        ipca.checar(linhas, 7060)


def test_checar_recusa_buraco_no_retangulo(recorte, monkeypatch) -> None:
    referencia = ipca.Referencia(3, frozenset({63, 66, 69, 2265}), 3)
    monkeypatch.setitem(ipca.REFERENCIA, 7060, referencia)
    linhas = ipca.transformar(recorte, 7060)
    ipca.checar(linhas, 7060)  # o recorte inteiro passa

    with pytest.raises(ipca.ChecagemError, match="35 combinações de 36"):
        ipca.checar(linhas[:-1], 7060)


def test_transformar_metadados_traduz_id_interno_para_codigo_da_cesta() -> None:
    linhas = ipca.transformar_metadados(METADADOS, 7060)

    assert linhas[3] == {
        "agregado": 7060,
        "id_categoria": 7173,
        "codigo": "1101002",
        "nome": "Arroz",
        "codigo_pai": "1101",
        "nivel": "subitem",
    }
    assert (linhas[0]["codigo"], linhas[0]["codigo_pai"], linhas[0]["nivel"]) == (
        "7169",
        None,
        "geral",
    )


def test_1737_nao_tem_cesta_e_passa_na_checagem() -> None:
    linhas = ipca.transformar_metadados({"classificacoes": []}, 1737)

    assert linhas == []
    ipca.checar_metadados(linhas, 1737)


def test_checar_metadados_recusa_cesta_truncada() -> None:
    with pytest.raises(ipca.ChecagemError, match="4 categorias nos metadados"):
        ipca.checar_metadados(ipca.transformar_metadados(METADADOS, 7060), 7060)
