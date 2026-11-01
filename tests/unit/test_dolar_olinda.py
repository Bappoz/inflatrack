"""Testes unitários puros da API Olinda (PTAX / BACEN) e validação da Bronze Dólar."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from inflatrack.bronze import dolar
from inflatrack.clients.dolar_olinda import OlindaClient, OlindaError

# ---------------------------------------------------------------------------
# Testes do cliente HTTP OlindaClient
# ---------------------------------------------------------------------------


def test_cliente_configura_parametros_timeout_e_valida_resposta() -> None:
    session = MagicMock()
    resposta = session.get.return_value
    resposta.json.return_value = {"value": [{"cotacaoVenda": 5.11, "cotacaoCompra": 5.10}]}

    resultado = OlindaClient(session).buscar_dolar("07-01-2024", "07-02-2024")

    assert resultado == [{"cotacaoVenda": 5.11, "cotacaoCompra": 5.10}]
    resposta.raise_for_status.assert_called_once_with()
    assert session.get.call_args.kwargs["timeout"] == 30.0
    assert session.get.call_args.kwargs["params"]["@dataInicial"] == "'07-01-2024'"
    assert session.get.call_args.kwargs["params"]["@dataFinalCotacao"] == "'07-02-2024'"
    assert session.get.call_args.kwargs["params"]["$format"] == "json"


def test_cliente_rejeita_payload_malformado() -> None:
    session = MagicMock()
    session.get.return_value.json.return_value = {"erro": "indisponível"}
    with pytest.raises(OlindaError, match="formato inesperado"):
        OlindaClient(session).buscar_dolar("07-01-2024", "07-02-2024")


def test_cliente_rejeita_payload_sem_lista() -> None:
    session = MagicMock()
    session.get.return_value.json.return_value = {"value": "nao_e_uma_lista"}
    with pytest.raises(OlindaError, match="formato inesperado"):
        OlindaClient(session).buscar_dolar("07-01-2024", "07-02-2024")


@patch("inflatrack.clients.dolar_olinda.time.sleep")
def test_cliente_erro_http_apos_retentativa(mock_sleep: MagicMock) -> None:
    session = MagicMock()
    resp_falha = MagicMock()
    resp_falha.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
    session.get.return_value = resp_falha

    with pytest.raises(requests.HTTPError):
        OlindaClient(session).buscar_dolar("07-01-2024", "07-02-2024")

    assert session.get.call_count == 2
    mock_sleep.assert_called_once_with(1)


@patch("inflatrack.clients.dolar_olinda.time.sleep")
def test_cliente_erro_timeout_apos_retentativa(mock_sleep: MagicMock) -> None:
    session = MagicMock()
    session.get.side_effect = requests.Timeout("Gateway Timeout")

    with pytest.raises(requests.Timeout):
        OlindaClient(session).buscar_dolar("07-01-2024", "07-02-2024")

    assert session.get.call_count == 2
    mock_sleep.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# Testes de transformação da Bronze (dolar.transformar)
# ---------------------------------------------------------------------------


def test_transformar_dolar_extrai_boletins_e_tipos() -> None:
    payload = {
        "value": [
            {
                "cotacaoCompra": 5.0123,
                "cotacaoVenda": 5.0129,
                "dataHoraCotacao": "2024-07-01 10:05:00",
                "tipoBoletim": "Abertura",
            },
            {
                "cotacaoCompra": 5.0500,
                "cotacaoVenda": 5.0510,
                "dataHoraCotacao": "2024-07-01 13:10:00",
                "tipoBoletim": "Fechamento PTAX",
            },
        ]
    }

    linhas = dolar.transformar(payload)

    assert len(linhas) == 2

    l1 = linhas[0]
    assert l1["cotacao_compra"] == 5.0123
    assert l1["cotacao_venda"] == 5.0129
    assert l1["tipo_boletim"] == "Abertura"
    assert l1["data_referencia"] == date(2024, 7, 1)
    assert l1["ano"] == 2024
    assert isinstance(l1["data_hora_cotacao"], datetime)

    l2 = linhas[1]
    assert l2["tipo_boletim"] == "Fechamento PTAX"
    assert l2["cotacao_venda"] == 5.0510


def test_transformar_dolar_rejeita_payload_vazio() -> None:
    with pytest.raises(OlindaError, match="não retornou cotações"):
        dolar.transformar({"value": []})

    with pytest.raises(OlindaError, match="não retornou cotações"):
        dolar.transformar([])


def test_transformar_dolar_rejeita_tipo_invalido() -> None:
    with pytest.raises(OlindaError, match="formato inesperado"):
        dolar.transformar("texto_invalido")  # type: ignore[arg-type]


def test_transformar_dolar_rejeita_item_sem_coluna_obrigatoria() -> None:
    # Faltando cotacaoVenda
    payload = {
        "value": [
            {"cotacaoCompra": 5.0, "dataHoraCotacao": "2024-07-01 10:00:00"}
        ]
    }
    with pytest.raises(OlindaError, match="sem as colunas esperadas"):
        dolar.transformar(payload)


def test_transformar_dolar_rejeita_cotacao_invalida() -> None:
    payload = {
        "value": [
            {
                "cotacaoCompra": "não-número",
                "cotacaoVenda": 5.10,
                "dataHoraCotacao": "2024-07-01 10:00:00",
            }
        ]
    }
    with pytest.raises(ValueError):
        dolar.transformar(payload)


# ---------------------------------------------------------------------------
# Testes de checagem de qualidade da Bronze (dolar.checar)
# ---------------------------------------------------------------------------


def test_checar_dolar_valido() -> None:
    linhas = [
        {
            "cotacao_compra": 5.10,
            "cotacao_venda": 5.11,
            "data_hora_cotacao": datetime(2024, 7, 1, 10, 0, tzinfo=UTC),
            "data_referencia": date(2024, 7, 1),
            "tipo_boletim": "Abertura",
            "ano": 2024,
        }
    ]
    # Não deve levantar nenhuma exceção
    dolar.checar(linhas)


def test_checar_dolar_vazio() -> None:
    with pytest.raises(dolar.ChecagemError, match="conjunto vazio"):
        dolar.checar([])


def test_checar_dolar_cotacao_negativa() -> None:
    linhas = [
        {
            "cotacao_compra": -5.10,
            "cotacao_venda": 5.11,
            "data_hora_cotacao": datetime(2024, 7, 1, 10, 0),
            "data_referencia": date(2024, 7, 1),
            "tipo_boletim": "Abertura",
            "ano": 2024,
        }
    ]
    with pytest.raises(dolar.ChecagemError, match="cotação não positiva"):
        dolar.checar(linhas)


def test_checar_dolar_cotacao_zero() -> None:
    linhas = [
        {
            "cotacao_compra": 0.0,
            "cotacao_venda": 5.11,
            "data_hora_cotacao": datetime(2024, 7, 1, 10, 0),
            "data_referencia": date(2024, 7, 1),
            "tipo_boletim": "Abertura",
            "ano": 2024,
        }
    ]
    with pytest.raises(dolar.ChecagemError, match="cotação não positiva"):
        dolar.checar(linhas)


def test_checar_dolar_spread_negativo() -> None:
    linhas = [
        {
            "cotacao_compra": 5.20,
            "cotacao_venda": 5.10,  # Compra > Venda
            "data_hora_cotacao": datetime(2024, 7, 1, 10, 0),
            "data_referencia": date(2024, 7, 1),
            "tipo_boletim": "Abertura",
            "ano": 2024,
        }
    ]
    with pytest.raises(dolar.ChecagemError, match="spread negativo"):
        dolar.checar(linhas)


def test_checar_dolar_ano_implausivel() -> None:
    linhas = [
        {
            "cotacao_compra": 5.10,
            "cotacao_venda": 5.11,
            "data_hora_cotacao": datetime(1990, 7, 1, 10, 0),
            "data_referencia": date(1990, 7, 1),
            "tipo_boletim": "Abertura",
            "ano": 1990,  # Antes do Plano Real (1994)
        }
    ]
    with pytest.raises(dolar.ChecagemError, match="ano implausível"):
        dolar.checar(linhas)
