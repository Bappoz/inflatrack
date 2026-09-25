import pytest
from unittest.mock import patch, MagicMock
from inflatrack.selic_sgs import SGSClient

@patch("inflatrack.selic_sgs.requests.Session")
def test_buscar_selic_sucesso(mock_session_class):
    """Garante que o cliente SGS extrai o valor da taxa corretamente."""
    mock_session_instance = MagicMock()
    mock_session_class.return_value = mock_session_instance
    
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"data": "01/07/2024", "valor": "0.039"}
    ]
    mock_session_instance.get.return_value = mock_response

    client = SGSClient()
    resultado = client.buscar_serie(11, "01/07/2024", "01/07/2024")

    assert mock_session_instance.get.called
    assert isinstance(resultado, list)
    assert len(resultado) == 1
    assert resultado[0]["valor"] == "0.039"
