from datetime import date
from unittest.mock import MagicMock

import duckdb
import pytest

from inflatrack.ingest_selic import carregar, transformar
from inflatrack.selic_sgs import SGSClient, SGSError


def test_cliente_configura_parametros_timeout_e_valida_resposta() -> None:
    session = MagicMock()
    resposta = session.get.return_value
    resposta.json.return_value = [{"data": "01/07/2024", "valor": "0.039"}]

    resultado = SGSClient(session).buscar_serie(11, "01/07/2024", "02/07/2024")

    assert resultado[0]["valor"] == "0.039"
    resposta.raise_for_status.assert_called_once_with()
    assert session.get.call_args.kwargs["timeout"] == 30.0
    assert session.get.call_args.kwargs["params"]["dataInicial"] == "01/07/2024"


def test_cliente_rejeita_payload_malformado() -> None:
    session = MagicMock()
    session.get.return_value.json.return_value = {"erro": "indisponível"}
    with pytest.raises(SGSError):
        SGSClient(session).buscar_serie(11)


def test_transformar_preserva_taxa_diaria_e_marca_dias_preenchidos() -> None:
    dados = [
        {"data": "28/06/2024", "valor": "0.039"},
        {"data": "01/07/2024", "valor": "0.040"},
    ]

    quadro = transformar(dados, date(2024, 6, 29), date(2024, 7, 1))

    assert quadro["taxa_dia_pct"].tolist() == [0.039, 0.039, 0.040]
    assert quadro["observado"].tolist() == [False, False, True]


def test_carga_selic_e_idempotente() -> None:
    quadro = transformar(
        [{"data": "01/07/2024", "valor": "0.039"}],
        date(2024, 7, 1),
        date(2024, 7, 1),
    )
    with duckdb.connect(":memory:") as conexao:
        assert carregar(conexao, quadro) == 1
        assert carregar(conexao, quadro) == 1
