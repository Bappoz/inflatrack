"""Cliente do Open-Meteo (clima provisório): parâmetros e leitura da resposta, sem rede."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from inflatrack.clients import open_meteo

FIXTURE = Path(__file__).parents[1] / "fixtures" / "clima" / "open_meteo_A001_A305.json"


@pytest.fixture
def payload() -> list[dict]:
    """Resposta real do archive-api para Brasília (A001) e Fortaleza (A305), 1 a 3/11/2026."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parametros_pedem_dia_utc_e_todas_as_coordenadas_numa_chamada() -> None:
    params = open_meteo.parametros_diarios(
        [(-15.78944, -47.92583), (-3.81583, -38.53778)], date(2026, 11, 1), date(2026, 11, 3)
    )

    assert params["latitude"] == "-15.78944,-3.81583"
    assert params["longitude"] == "-47.92583,-38.53778"
    assert (params["start_date"], params["end_date"]) == ("2026-11-01", "2026-11-03")
    assert params["timezone"] == "GMT"  # o mesmo dia UTC do BDMEP
    assert set(params["daily"].split(",")) == set(open_meteo.VARIAVEIS_DIARIAS)


def test_resposta_vira_uma_linha_por_estacao_e_dia_na_ordem_pedida(payload) -> None:
    linhas = open_meteo.transformar_diario(payload, ["A001", "A305"])

    assert len(linhas) == 6
    assert [linha["estacao_id"] for linha in linhas] == ["A001"] * 3 + ["A305"] * 3
    fortaleza = linhas[3]
    assert fortaleza["data_referencia"] == date(2026, 11, 1)
    assert fortaleza["temp_media"] == 28.5
    assert fortaleza["temp_min"] <= fortaleza["temp_media"] <= fortaleza["temp_max"]
    assert fortaleza["precipitacao_total_mm"] == 0.0  # zero é medida, não ausência
    assert fortaleza["latitude_grade"] == pytest.approx(-3.8, abs=0.1)


def test_uma_coordenada_vem_como_objeto_e_nao_como_lista(payload) -> None:
    assert len(open_meteo.transformar_diario(payload[0], ["A001"])) == 3


def test_numero_de_locais_diferente_do_pedido_falha(payload) -> None:
    with pytest.raises(open_meteo.OpenMeteoError, match="2 locais para 3"):
        open_meteo.transformar_diario(payload, ["A001", "A305", "A701"])


def test_variavel_faltando_falha_explicitamente(payload) -> None:
    del payload[0]["daily"]["precipitation_sum"]

    with pytest.raises(open_meteo.OpenMeteoError, match="precipitation_sum"):
        open_meteo.transformar_diario(payload, ["A001", "A305"])


def test_dia_sem_nenhum_valor_nao_vira_linha(payload) -> None:
    for nome in open_meteo.VARIAVEIS_DIARIAS:
        payload[0]["daily"][nome][2] = None

    linhas = open_meteo.transformar_diario(payload, ["A001", "A305"])

    assert [linha["data_referencia"].day for linha in linhas if linha["estacao_id"] == "A001"] == [
        1,
        2,
    ]


def test_cliente_devolve_url_e_corpo_e_falha_em_erro_http() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        if "start_date=2026-01-01" in str(request.url):
            return httpx.Response(400, json={"error": True, "reason": "data inválida"})
        return httpx.Response(200, text="[]")

    cliente = open_meteo.OpenMeteoClient(httpx.Client(transport=httpx.MockTransport(responder)))

    url, corpo = cliente.buscar_diario([(-15.8, -47.9)], date(2026, 11, 1), date(2026, 11, 2))
    assert url.startswith(open_meteo.URL_ARQUIVO) and "latitude=-15.80000" in url
    assert corpo == "[]"
    with pytest.raises(open_meteo.OpenMeteoError, match="400"):
        cliente.buscar_diario([(-15.8, -47.9)], date(2026, 1, 1), date(2026, 1, 2))
