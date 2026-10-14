from pathlib import Path

import duckdb
import pytest

from inflatrack import bronze_pib_china
from inflatrack.ingest_pib_china import WorldBankError, transformar
from inflatrack.load_pib_china import carregar


def payload(*observacoes: tuple[str, float | None]) -> list:
    return [
        {"page": 1, "pages": 1},
        [{"date": ano, "value": valor} for ano, valor in observacoes],
    ]


def test_transformar_combina_series_e_preserva_ausentes() -> None:
    quadro = transformar(
        payload(("2024", 5.0), ("2023", 4.5)),
        payload(("2024", 18_000.0), ("2022", None)),
    )

    assert quadro["ano"].tolist() == [2022, 2023, 2024]
    assert quadro.loc[quadro["ano"] == 2024, "crescimento_pib_pct"].item() == 5.0
    assert quadro.loc[quadro["ano"] == 2024, "pib_usd"].item() == 18_000.0
    assert quadro.loc[quadro["ano"] == 2022, "pib_usd"].isna().item()


def test_transformar_rejeita_resposta_malformada() -> None:
    with pytest.raises(WorldBankError):
        transformar([], payload(("2024", 18_000.0)))


def test_carregar_faz_upsert_idempotente(tmp_path: Path) -> None:
    parquet = tmp_path / "pib_china.parquet"
    transformar(payload(("2024", 5.0)), payload(("2024", 18_000.0))).to_parquet(parquet)

    with duckdb.connect(":memory:") as conexao:
        assert carregar(conexao, parquet) == 1
        assert carregar(conexao, parquet) == 1
        assert conexao.execute(
            "SELECT crescimento_pib_pct, pib_usd FROM pib_china WHERE ano = 2024"
        ).fetchone() == (5.0, 18_000.0)


# --- Testes da Bronze em Delta (E2) -----------------------------------------------


def test_bronze_transformar_formato_longo() -> None:
    dados = [
        {"page": 1, "pages": 1},
        [
            {
                "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
                "country": {"id": "CN", "value": "China"},
                "countryiso3code": "CHN",
                "date": "2024",
                "value": 5.2,
                "unit": "",
                "obs_status": "",
                "decimal": 1,
            },
            {
                "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
                "country": {"id": "CN", "value": "China"},
                "countryiso3code": "CHN",
                "date": "2025",
                "value": None,
                "unit": "",
                "obs_status": "",
                "decimal": 1,
            },
        ],
    ]
    linhas = bronze_pib_china.transformar(dados)
    assert len(linhas) == 2
    assert linhas[0]["indicador"] == "NY.GDP.MKTP.KD.ZG"
    assert linhas[0]["ano"] == 2024
    assert linhas[0]["valor"] == 5.2
    assert linhas[0]["pais_nome"] == "China"
    assert linhas[1]["ano"] == 2025
    assert linhas[1]["valor"] is None


def test_bronze_checagem_rejeita_duplicidade() -> None:
    linhas = [
        {"indicador": "NY.GDP.MKTP.KD.ZG", "ano": 2020, "valor": 2.2},
        {"indicador": "NY.GDP.MKTP.KD.ZG", "ano": 2020, "valor": 2.2},
    ]
    with pytest.raises(bronze_pib_china.ChecagemError, match="duplicidade"):
        bronze_pib_china.checar(linhas)


def test_bronze_gravacao_idempotente_em_delta(tmp_path: Path) -> None:
    # Simulando 55 anos para passar na validação de volume mínimo
    anos_extras = [
        f'{{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}}, '
        f'"country": {{"id": "CN", "value": "China"}}, "date": "{ano}", "value": 5.0}}'
        for ano in range(1962, 2020)
    ]
    corpo_completo = f"""[
        {{"page": 1, "pages": 1, "per_page": 1000, "total": {len(anos_extras) + 2}}},
        [
            {{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}},
              "country": {{"id": "CN", "value": "China"}}, "date": "1961", "value": -27.27}},
            {",".join(anos_extras)},
            {{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}},
              "country": {{"id": "CN", "value": "China"}}, "date": "2020", "value": 2.24}}
        ]
    ]"""

    gravacao1 = bronze_pib_china.gravar(
        destino=tmp_path,
        indicador="NY.GDP.MKTP.KD.ZG",
        requisicao="https://api.worldbank.org/test",
        corpo=corpo_completo,
    )
    assert gravacao1.resposta_nova is True
    assert gravacao1.linhas_novas == 60

    # Segunda gravação do mesmo corpo: resposta não é regravada e observações novas são 0
    gravacao2 = bronze_pib_china.gravar(
        destino=tmp_path,
        indicador="NY.GDP.MKTP.KD.ZG",
        requisicao="https://api.worldbank.org/test",
        corpo=corpo_completo,
    )
    assert gravacao2.resposta_nova is False
    assert gravacao2.linhas_novas == 0
