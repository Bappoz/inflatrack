from datetime import date

import pytest

from inflatrack.common.conversores import converter_centavos, converter_data


@pytest.mark.parametrize(
    ("texto", "centavos"),
    [("R$ 1.234,56", 123456), ("12,5", 1250), ("7.95", 795), ("10", 1000), (" 3,00 ", 300)],
)
def test_converter_centavos_aceita_formato_brasileiro_e_ponto(texto: str, centavos: int) -> None:
    assert converter_centavos(texto) == centavos


@pytest.mark.parametrize("texto", ["7,955", "7,950", "1.250", "", "  ", "-1,00", "abc", "1,2,3"])
def test_converter_centavos_recusa_valor_invalido(texto: str) -> None:
    with pytest.raises(ValueError):
        converter_centavos(texto)


@pytest.mark.parametrize("texto", ["19/11/2026", "2026-11-19"])
def test_converter_data_aceita_iso_e_brasileiro(texto: str) -> None:
    assert converter_data(texto) == date(2026, 11, 19)


@pytest.mark.parametrize("texto", ["2026/13/01", "", "31/02/2026"])
def test_converter_data_recusa_data_invalida(texto: str) -> None:
    with pytest.raises(ValueError):
        converter_data(texto)
