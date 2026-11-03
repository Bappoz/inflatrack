from unittest.mock import MagicMock

import httpx
import pytest

from inflatrack.clients.worldbank import (
    INDICADOR_CRESCIMENTO,
    INDICADOR_PIB_USD,
    PAISES,
    WorldBankClient,
    WorldBankError,
)
from inflatrack.common.bronze import Resposta


def test_url_publica_formata_corretamente() -> None:
    url = WorldBankClient.url_publica("chn", INDICADOR_CRESCIMENTO, per_page=1000)
    assert "country/CHN/indicator/NY.GDP.MKTP.KD.ZG" in url
    assert "format=json" in url
    assert "per_page=1000" in url


def test_paises_e_indicadores_padrao_definidos() -> None:
    assert "CHN" in PAISES
    assert "USA" in PAISES
    assert "RUS" in PAISES
    assert INDICADOR_CRESCIMENTO == "NY.GDP.MKTP.KD.ZG"
    assert INDICADOR_PIB_USD == "NY.GDP.MKTP.CD"


def test_buscar_resposta_sucesso() -> None:
    cliente_mock = MagicMock(spec=httpx.Client)
    resposta_mock = MagicMock(spec=httpx.Response)
    resposta_mock.status_code = 200
    resposta_mock.headers = {"content-type": "application/json"}
    resposta_mock.text = '[{"page": 1, "pages": 1}, [{"date": "2024", "value": 5.2}]]'
    cliente_mock.get.return_value = resposta_mock

    wb = WorldBankClient(cliente=cliente_mock)
    resp = wb.buscar_resposta("CHN", INDICADOR_CRESCIMENTO)

    assert isinstance(resp, Resposta)
    assert resp.status_http == 200
    assert resp.tipo_conteudo == "application/json"
    assert "5.2" in resp.corpo
    cliente_mock.get.assert_called_once_with(
        "https://api.worldbank.org/v2/country/CHN/indicator/NY.GDP.MKTP.KD.ZG",
        params={"format": "json", "per_page": 1000},
    )


def test_buscar_payload_sucesso() -> None:
    cliente_mock = MagicMock(spec=httpx.Client)
    resposta_mock = MagicMock(spec=httpx.Response)
    resposta_mock.status_code = 200
    resposta_mock.headers = {"content-type": "application/json"}
    resposta_mock.text = '[{"page": 1}, [{"date": "2024", "value": 5.2}]]'
    cliente_mock.get.return_value = resposta_mock

    wb = WorldBankClient(cliente=cliente_mock)
    payload = wb.buscar_payload("USA", INDICADOR_PIB_USD)

    assert isinstance(payload, list)
    assert len(payload) == 2
    assert payload[1][0]["value"] == 5.2


def test_buscar_payload_estrutura_invalida_lanca_erro() -> None:
    cliente_mock = MagicMock(spec=httpx.Client)
    resposta_mock = MagicMock(spec=httpx.Response)
    resposta_mock.status_code = 200
    resposta_mock.headers = {"content-type": "application/json"}
    resposta_mock.text = '{"message": [{"id": "120", "key": "Not found"}]}'
    cliente_mock.get.return_value = resposta_mock

    wb = WorldBankClient(cliente=cliente_mock)
    with pytest.raises(WorldBankError, match="Formato inesperado"):
        wb.buscar_payload("CHN", INDICADOR_CRESCIMENTO)


def test_buscar_resposta_erro_http_lanca_erro() -> None:
    cliente_mock = MagicMock(spec=httpx.Client)
    cliente_mock.get.side_effect = httpx.HTTPStatusError(
        "404 Not Found",
        request=MagicMock(),
        response=MagicMock(status_code=404),
    )

    wb = WorldBankClient(cliente=cliente_mock)
    with pytest.raises(WorldBankError, match="Erro na requisição ao Banco Mundial"):
        wb.buscar_resposta("RUS", INDICADOR_CRESCIMENTO)


def test_context_manager_fecha_cliente_proprio() -> None:
    with WorldBankClient() as wb:
        assert wb.cliente is not None
    # Cliente foi fechado
    assert wb.cliente.is_closed
