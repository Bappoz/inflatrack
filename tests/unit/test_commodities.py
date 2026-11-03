"""Commodities (Alpha Vantage): validação e transformação em memória, com recortes reais.

A gravação nas tabelas Delta fica em tests/integration/test_commodities.py.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from inflatrack.bronze import commodities
from inflatrack.clients.alphavantage import AlphaVantageClient
from inflatrack.common.bronze import ChecagemError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "commodities"


def _dados(nome: str) -> dict:
    return json.loads((FIXTURES / f"{nome}-recorte.json").read_text(encoding="utf-8"))


def test_transformar_mantem_ponto_como_preco_nulo() -> None:
    linhas = commodities.transformar("CORN", _dados("corn"))

    assert len(linhas) == 7
    ausentes = [linha for linha in linhas if linha["preco"] is None]
    assert len(ausentes) == 2
    assert {linha["unidade"] for linha in linhas} == {"dollar per metric ton"}
    assert linhas[0]["intervalo"] == "monthly"


def test_preco_negativo_do_wti_e_mantido() -> None:
    """Abril de 2020: o WTI fechou negativo. Descartar ≤ 0 é regra do dbt."""
    linhas = commodities.transformar("WTI", _dados("wti"))
    negativo = next(linha for linha in linhas if linha["data_referencia"] == date(2020, 4, 20))
    assert negativo["preco"] < 0


@pytest.mark.parametrize(
    "corpo",
    [
        {"Information": "We have detected your API key ... 25 requests per day."},
        {"Error Message": "Invalid API call."},
        {"name": "x", "interval": "monthly", "unit": "u"},
        {"name": "x", "interval": "monthly", "unit": "u", "data": []},
        {
            "name": "x",
            "interval": "daily",
            "unit": "u",
            "data": [{"date": "2026-01-01", "value": "1"}],
        },
        ["não", "é", "objeto"],
    ],
    ids=["cota-esgotada", "erro", "sem-data", "lista-vazia", "intervalo-errado", "nao-objeto"],
)
def test_validar_recusa_resposta_sem_serie(corpo: object) -> None:
    with pytest.raises(ChecagemError):
        commodities.validar("CORN", corpo)


def test_preco_que_nao_e_numero_e_recusado() -> None:
    dados = _dados("corn")
    dados["data"][0]["value"] = "abc"
    with pytest.raises(ChecagemError, match="não é número"):
        commodities.transformar("CORN", dados)


def test_checar_recusa_data_repetida() -> None:
    linhas = commodities.transformar("CORN", _dados("corn"))
    with pytest.raises(ChecagemError, match="datas repetidas"):
        commodities.checar("CORN", [*linhas, linhas[0]])


def test_checar_recusa_volume_abaixo_do_minimo() -> None:
    linhas = commodities.transformar("CORN", _dados("corn"))
    with pytest.raises(ChecagemError, match="mínimo 559"):
        commodities.checar("CORN", linhas)


def test_requisicao_guardada_nao_tem_a_chave() -> None:
    url = AlphaVantageClient.url_publica("WTI", "daily")
    assert "apikey" not in url
    assert url.endswith("function=WTI&interval=daily")


def test_as_nove_commodities_tem_volume_minimo() -> None:
    assert set(commodities.COMMODITY_CONFIGS) == set(commodities.LINHAS_MINIMAS)
    assert len(commodities.COMMODITY_CONFIGS) == 9
