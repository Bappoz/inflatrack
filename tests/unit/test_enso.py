"""Leitura e checagem do RONI (NOAA), sem rede."""

from datetime import date
from pathlib import Path

import pytest

from inflatrack.bronze import enso

FIXTURE = Path(__file__).parents[1] / "fixtures" / "enso" / "RONI.ascii.txt"


@pytest.fixture
def texto() -> str:
    """Arquivo real do NOAA, de DJF/1950 a ASO/2026."""
    return FIXTURE.read_text(encoding="utf-8")


def test_temporada_vai_para_o_mes_central(texto) -> None:
    linhas = enso.transformar(texto)

    assert linhas[0] == {
        "temporada": "DJF",
        "ano": 1950,
        "mes_referencia": date(1950, 1, 1),
        "roni": -1.19,
    }
    ndj = next(x for x in linhas if x["temporada"] == "NDJ" and x["ano"] == 1950)
    assert ndj["mes_referencia"] == date(1950, 12, 1)  # nov/1950 a jan/1951
    assert linhas[-1]["mes_referencia"] == date(2026, 9, 1)  # ASO/2026


def test_serie_real_passa_na_checagem(texto) -> None:
    enso.checar(enso.transformar(texto))


def test_cabecalho_diferente_e_recusado(texto) -> None:
    with pytest.raises(enso.ChecagemError, match="Cabeçalho"):
        enso.transformar(texto.replace("SEAS", "SEASON", 1))


def test_linha_fora_do_formato_e_erro_e_nao_e_pulada(texto) -> None:
    with pytest.raises(enso.ChecagemError, match="fora do formato"):
        enso.transformar(texto.replace("JFM  1950", "XYZ  1950", 1))


def test_buraco_na_serie_e_recusado(texto) -> None:
    linhas = enso.transformar(texto)
    del linhas[500]

    with pytest.raises(enso.ChecagemError, match="buraco"):
        enso.checar(linhas)


def test_valor_fora_da_faixa_e_recusado(texto) -> None:
    linhas = enso.transformar(texto)
    linhas[10]["roni"] = 9.9

    with pytest.raises(enso.ChecagemError, match="fora da faixa"):
        enso.checar(linhas)


def test_serie_curta_e_recusada(texto) -> None:
    with pytest.raises(enso.ChecagemError, match="mínimo"):
        enso.checar(enso.transformar(texto)[:100])
