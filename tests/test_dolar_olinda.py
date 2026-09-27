from datetime import date
from unittest.mock import MagicMock

import duckdb
import pytest

from inflatrack.dolar_olinda import OlindaClient, OlindaError
from inflatrack.ingest_dolar import carregar, transformar


def test_cliente_configura_parametros_timeout_e_valida_resposta() -> None:
    session = MagicMock()
    resposta = session.get.return_value
    resposta.json.return_value = {"value": [{"cotacaoVenda": 5.11}]}

    resultado = OlindaClient(session).buscar_dolar("07-01-2024", "07-02-2024")

    assert resultado == [{"cotacaoVenda": 5.11}]
    resposta.raise_for_status.assert_called_once_with()
    assert session.get.call_args.kwargs["timeout"] == 30.0
    assert session.get.call_args.kwargs["params"]["@dataInicial"] == "'07-01-2024'"


def test_cliente_rejeita_payload_malformado() -> None:
    session = MagicMock()
    session.get.return_value.json.return_value = {"erro": "indisponível"}
    with pytest.raises(OlindaError):
        OlindaClient(session).buscar_dolar("07-01-2024", "07-02-2024")


def test_transformar_escolhe_ultimo_boletim_e_marca_dias_preenchidos() -> None:
    dados = [
        {
            "dataHoraCotacao": "2024-06-28 10:00:00",
            "cotacaoCompra": 5.0,
            "cotacaoVenda": 5.1,
        },
        {
            "dataHoraCotacao": "2024-06-28 13:00:00",
            "cotacaoCompra": 5.2,
            "cotacaoVenda": 5.3,
        },
        {
            "dataHoraCotacao": "2024-07-01 13:00:00",
            "cotacaoCompra": 5.4,
            "cotacaoVenda": 5.5,
        },
    ]

    quadro = transformar(dados, date(2024, 6, 29), date(2024, 7, 1))

    assert quadro["cotacao_venda"].tolist() == [5.3, 5.3, 5.5]
    assert quadro["observado"].tolist() == [False, False, True]


def test_carga_dolar_e_idempotente() -> None:
    quadro = transformar(
        [
            {
                "dataHoraCotacao": "2024-07-01 13:00:00",
                "cotacaoCompra": 5.4,
                "cotacaoVenda": 5.5,
            }
        ],
        date(2024, 7, 1),
        date(2024, 7, 1),
    )
    with duckdb.connect(":memory:") as conexao:
        assert carregar(conexao, quadro) == 1
        assert carregar(conexao, quadro) == 1
