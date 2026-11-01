"""Testes unitários puros da API SGS (Série 11 - Selic / BACEN) e validação da Bronze Selic."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import requests

from inflatrack.bronze import selic
from inflatrack.clients.selic_sgs import SGSClient, SGSError

# ---------------------------------------------------------------------------
# Testes do cliente HTTP SGSClient
# ---------------------------------------------------------------------------


def test_cliente_configura_parametros_timeout_e_valida_resposta() -> None:
    session = MagicMock()
    resposta = session.get.return_value
    resposta.json.return_value = [{"data": "01/07/2024", "valor": "0.039"}]

    resultado = SGSClient(session).buscar_serie(11, "01/07/2024", "02/07/2024")

    assert resultado[0]["valor"] == "0.039"
    resposta.raise_for_status.assert_called_once_with()
    assert session.get.call_args.kwargs["timeout"] == 30.0
    assert session.get.call_args.kwargs["params"]["dataInicial"] == "01/07/2024"
    assert session.get.call_args.kwargs["params"]["dataFinal"] == "02/07/2024"
    assert session.get.call_args.kwargs["params"]["formato"] == "json"
    assert "https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados" in session.get.call_args.args[0]


def test_cliente_rejeita_payload_malformado() -> None:
    session = MagicMock()
    session.get.return_value.json.return_value = {"erro": "indisponível"}
    with pytest.raises(SGSError, match="formato inesperado"):
        SGSClient(session).buscar_serie(11)


@patch("inflatrack.clients.selic_sgs.time.sleep")
def test_cliente_erro_http_apos_retentativa(mock_sleep: MagicMock) -> None:
    session = MagicMock()
    resp_falha = MagicMock()
    resp_falha.raise_for_status.side_effect = requests.HTTPError("500 Internal Error")
    session.get.return_value = resp_falha

    with pytest.raises(requests.HTTPError):
        SGSClient(session).buscar_serie(11)

    assert session.get.call_count == 2
    mock_sleep.assert_called_once_with(1)


@patch("inflatrack.clients.selic_sgs.time.sleep")
def test_cliente_erro_timeout_apos_retentativa(mock_sleep: MagicMock) -> None:
    session = MagicMock()
    session.get.side_effect = requests.Timeout("Gateway Timeout")

    with pytest.raises(requests.Timeout):
        SGSClient(session).buscar_serie(11)

    assert session.get.call_count == 2
    mock_sleep.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# Testes de transformação da Bronze (selic.transformar)
# ---------------------------------------------------------------------------


def test_transformar_selic_extrai_taxas_e_anualiza() -> None:
    payload = [
        {"data": "02/01/2020", "valor": "0.017089"},
        {"data": "03/01/2020", "valor": "0.017089"},
    ]

    linhas = selic.transformar(payload)

    assert len(linhas) == 2

    l1 = linhas[0]
    assert l1["data_referencia"] == date(2020, 1, 2)
    assert l1["taxa_dia_pct"] == pytest.approx(0.017089)
    # Taxa anualizada base 252 dias úteis: ((1 + 0.017089/100)^252 - 1) * 100
    assert l1["taxa_anualizada_pct"] == pytest.approx(4.40, abs=0.01)
    assert l1["ano"] == 2020

    l2 = linhas[1]
    assert l2["data_referencia"] == date(2020, 1, 3)
    assert l2["ano"] == 2020


def test_transformar_selic_rejeita_lista_vazia() -> None:
    with pytest.raises(SGSError, match="não retornou observações"):
        selic.transformar([])


def test_transformar_selic_rejeita_item_nao_dict() -> None:
    with pytest.raises(SGSError, match="não é um dicionário"):
        selic.transformar(["item_invalido"])  # type: ignore[list-item]


def test_transformar_selic_rejeita_item_sem_colunas() -> None:
    with pytest.raises(SGSError, match="sem as colunas esperadas"):
        selic.transformar([{"data": "02/01/2020"}])

    with pytest.raises(SGSError, match="sem as colunas esperadas"):
        selic.transformar([{"valor": "0.017"}])


def test_transformar_selic_rejeita_data_malformada() -> None:
    with pytest.raises(SGSError, match="data inválida"):
        selic.transformar([{"data": "2020-01-02", "valor": "0.017"}])


def test_transformar_selic_rejeita_valor_nao_numerico() -> None:
    with pytest.raises(SGSError, match="valor numérico inválido"):
        selic.transformar([{"data": "02/01/2020", "valor": "nao_numero"}])


# ---------------------------------------------------------------------------
# Testes de checagem de qualidade da Bronze (selic.checar)
# ---------------------------------------------------------------------------


def test_checar_selic_valida() -> None:
    linhas = [
        {
            "data_referencia": date(2020, 1, 2),
            "taxa_dia_pct": 0.017089,
            "taxa_anualizada_pct": 4.40,
            "ano": 2020,
        }
    ]
    # Não deve levantar nenhuma exceção
    selic.checar(linhas)


def test_checar_selic_vazio() -> None:
    with pytest.raises(selic.ChecagemError, match="conjunto vazio"):
        selic.checar([])


def test_checar_selic_taxa_negativa() -> None:
    linhas = [
        {
            "data_referencia": date(2020, 1, 2),
            "taxa_dia_pct": -0.01,
            "taxa_anualizada_pct": -2.0,
            "ano": 2020,
        }
    ]
    with pytest.raises(selic.ChecagemError, match="fora da faixa válida"):
        selic.checar(linhas)


def test_checar_selic_taxa_zero() -> None:
    linhas = [
        {
            "data_referencia": date(2020, 1, 2),
            "taxa_dia_pct": 0.0,
            "taxa_anualizada_pct": 0.0,
            "ano": 2020,
        }
    ]
    with pytest.raises(selic.ChecagemError, match="fora da faixa válida"):
        selic.checar(linhas)


def test_checar_selic_taxa_maior_que_um_por_cento_ao_dia() -> None:
    # Taxa anualizada inserida erroneamente como diária (> 1.0% ao dia)
    linhas = [
        {
            "data_referencia": date(2020, 1, 2),
            "taxa_dia_pct": 13.75,
            "taxa_anualizada_pct": 13.75,
            "ano": 2020,
        }
    ]
    with pytest.raises(selic.ChecagemError, match="fora da faixa válida"):
        selic.checar(linhas)


def test_checar_selic_ano_implausivel() -> None:
    linhas = [
        {
            "data_referencia": date(1980, 1, 2),
            "taxa_dia_pct": 0.05,
            "taxa_anualizada_pct": 10.0,
            "ano": 1980,  # Antes da criação da Selic moderna (1986)
        }
    ]
    with pytest.raises(selic.ChecagemError, match="ano implausível"):
        selic.checar(linhas)
