from pathlib import Path

import pytest

from inflatrack import bronze_pib_russia


def test_bronze_pib_russia_transformar() -> None:
    dados = [
        {"page": 1, "pages": 1},
        [
            {
                "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
                "country": {"id": "RU", "value": "Russian Federation"},
                "countryiso3code": "RUS",
                "date": "2024",
                "value": 3.6,
                "unit": "",
                "obs_status": "",
                "decimal": 1,
            },
            {
                "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
                "country": {"id": "RU", "value": "Russian Federation"},
                "countryiso3code": "RUS",
                "date": "1975",
                "value": None,
                "unit": "",
                "obs_status": "",
                "decimal": 1,
            },
        ],
    ]
    linhas = bronze_pib_russia.transformar(dados)
    assert len(linhas) == 2
    assert linhas[0]["indicador"] == "NY.GDP.MKTP.KD.ZG"
    assert linhas[0]["ano"] == 2024
    assert linhas[0]["valor"] == 3.6
    assert linhas[0]["pais_nome"] == "Russian Federation"
    assert linhas[1]["ano"] == 1975
    assert linhas[1]["valor"] is None


def test_bronze_pib_russia_checagem_rejeita_duplicidade() -> None:
    linhas = [
        {"indicador": "NY.GDP.MKTP.KD.ZG", "ano": 2020, "valor": -2.7},
        {"indicador": "NY.GDP.MKTP.KD.ZG", "ano": 2020, "valor": -2.7},
    ]
    with pytest.raises(bronze_pib_russia.ChecagemError, match="duplicidade"):
        bronze_pib_russia.checar(linhas)


def test_bronze_pib_russia_gravacao_idempotente(tmp_path: Path) -> None:
    # 30 anos nulos pré-1990 + 30 anos com valor pós-1990
    anos_pre_1990 = [
        f'{{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}}, '
        f'"country": {{"id": "RU", "value": "Russian Federation"}}, '
        f'"date": "{ano}", "value": null}}'
        for ano in range(1960, 1990)
    ]
    anos_pos_1990 = [
        f'{{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}}, '
        f'"country": {{"id": "RU", "value": "Russian Federation"}}, "date": "{ano}", "value": 2.5}}'
        for ano in range(1990, 2020)
    ]
    todos_anos = anos_pre_1990 + anos_pos_1990
    corpo_completo = f"""[
        {{"page": 1, "pages": 1, "per_page": 1000, "total": {len(todos_anos)}}},
        [
            {",".join(todos_anos)}
        ]
    ]"""

    gravacao1 = bronze_pib_russia.gravar(
        destino=tmp_path,
        indicador="NY.GDP.MKTP.KD.ZG",
        requisicao="https://api.worldbank.org/test-rus",
        corpo=corpo_completo,
    )
    assert gravacao1.resposta_nova is True
    assert gravacao1.linhas_novas == 60

    gravacao2 = bronze_pib_russia.gravar(
        destino=tmp_path,
        indicador="NY.GDP.MKTP.KD.ZG",
        requisicao="https://api.worldbank.org/test-rus",
        corpo=corpo_completo,
    )
    assert gravacao2.resposta_nova is False
    assert gravacao2.linhas_novas == 0
