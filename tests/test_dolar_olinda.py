import pytest
from unittest.mock import patch, MagicMock
from inflatrack.dolar_olinda import OlindaClient

@patch("inflatrack.dolar_olinda.requests.get")
def test_buscar_dolar_sucesso(mock_get):
    """Garante que o cliente Olinda processa corretamente um boletim com dados."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "value": [
            {"cotacaoCompra": 5.10, "cotacaoVenda": 5.11, "dataHoraCotacao": "2024-07-01 13:00:00"}
        ]
    }
    mock_get.return_value = mock_response

    client = OlindaClient()
    resultado = client.buscar_dolar("07-01-2024", "07-01-2024")

    assert mock_get.called
    assert isinstance(resultado, list)
    assert len(resultado) == 1
    assert resultado[0]["cotacaoVenda"] == 5.11

@patch("inflatrack.dolar_olinda.requests.get")
def test_buscar_dolar_vazio(mock_get):
    """Garante que o cliente lida perfeitamente com dias sem pregão (feriados/finais de semana)."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"value": []}
    mock_get.return_value = mock_response

    client = OlindaClient()
    resultado = client.buscar_dolar("12-25-2024", "12-25-2024")
    assert resultado == []
