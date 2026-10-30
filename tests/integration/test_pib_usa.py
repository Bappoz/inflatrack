from pathlib import Path

import pytest

from inflatrack import bronze_pib_usa


def test_bronze_pib_usa_transformar() -> None:
    dados = [
        {"page": 1, "pages": 1},
        [
            {
                "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
                "country": {"id": "US", "value": "United States"},
                "countryiso3code": "USA",
                "date": "2024",
                "value": 2.8,
                "unit": "",
                "obs_status": "",
                "decimal": 1,
            },
            {
                "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
                "country": {"id": "US", "value": "United States"},
                "countryiso3code": "USA",
                "date": "2025",
                "value": None,
                "unit": "",
                "obs_status": "",
                "decimal": 1,
            },
        ],
    ]
    linhas = bronze_pib_usa.transformar(dados)
    assert len(linhas) == 2
    assert linhas[0]["indicador"] == "NY.GDP.MKTP.KD.ZG"
    assert linhas[0]["ano"] == 2024
    assert linhas[0]["valor"] == 2.8
    assert linhas[0]["pais_nome"] == "United States"
    assert linhas[1]["ano"] == 2025
    assert linhas[1]["valor"] is None


def test_bronze_pib_usa_checagem_rejeita_duplicidade() -> None:
    linhas = [
        {"indicador": "NY.GDP.MKTP.KD.ZG", "ano": 2020, "valor": -2.2},
        {"indicador": "NY.GDP.MKTP.KD.ZG", "ano": 2020, "valor": -2.2},
    ]
    with pytest.raises(bronze_pib_usa.ChecagemError, match="duplicidade"):
        bronze_pib_usa.checar(linhas)


def test_bronze_pib_usa_gravacao_idempotente(tmp_path: Path) -> None:
    anos_extras = [
        f'{{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}}, '
        f'"country": {{"id": "US", "value": "United States"}}, "date": "{ano}", "value": 3.0}}'
        for ano in range(1962, 2020)
    ]
    corpo_completo = f"""[
        {{"page": 1, "pages": 1, "per_page": 1000, "total": {len(anos_extras) + 2}}},
        [
            {{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}},
              "country": {{"id": "US", "value": "United States"}}, "date": "1961", "value": 2.3}},
            {",".join(anos_extras)},
            {{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}},
              "country": {{"id": "US", "value": "United States"}}, "date": "2020", "value": -2.2}}
        ]
    ]"""

    gravacao1 = bronze_pib_usa.gravar(
        destino=tmp_path,
        indicador="NY.GDP.MKTP.KD.ZG",
        requisicao="https://api.worldbank.org/test-usa",
        corpo=corpo_completo,
    )
    assert gravacao1.resposta_nova is True
    assert gravacao1.linhas_novas == 60

    gravacao2 = bronze_pib_usa.gravar(
        destino=tmp_path,
        indicador="NY.GDP.MKTP.KD.ZG",
        requisicao="https://api.worldbank.org/test-usa",
        corpo=corpo_completo,
    )
    assert gravacao2.resposta_nova is False
    assert gravacao2.linhas_novas == 0
