import pytest

from inflatrack.bronze.pib_internacional import (
    ChecagemError,
    WorldBankError,
    checar,
    diretorio_padrao_pais,
    raw_dir_padrao_pais,
    sufixo_pais,
    transformar,
    transformar_largo,
)


def _payload_simples(*observacoes: tuple[str, float | None]) -> list:
    return [
        {"page": 1, "pages": 1},
        [{"date": ano, "value": valor} for ano, valor in observacoes],
    ]


# --- Testes de Transformação em Formato Longo (Bronze) ---------------------------


@pytest.mark.parametrize(
    ("pais_id", "pais_nome", "iso3", "valor"),
    [
        ("CN", "China", "CHN", 5.2),
        ("US", "United States", "USA", 2.8),
        ("RU", "Russian Federation", "RUS", 3.6),
    ],
)
def test_transformar_formato_longo_todos_os_paises(
    pais_id: str, pais_nome: str, iso3: str, valor: float
) -> None:
    dados = [
        {"page": 1, "pages": 1},
        [
            {
                "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
                "country": {"id": pais_id, "value": pais_nome},
                "countryiso3code": iso3,
                "date": "2024",
                "value": valor,
                "unit": "",
                "obs_status": "",
                "decimal": 1,
            },
            {
                "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
                "country": {"id": pais_id, "value": pais_nome},
                "countryiso3code": iso3,
                "date": "2025",
                "value": None,
                "unit": "",
                "obs_status": "",
                "decimal": 1,
            },
        ],
    ]
    linhas = transformar(dados)
    assert len(linhas) == 2
    assert linhas[0]["indicador"] == "NY.GDP.MKTP.KD.ZG"
    assert linhas[0]["ano"] == 2024
    assert linhas[0]["valor"] == valor
    assert linhas[0]["pais_nome"] == pais_nome
    assert linhas[0]["pais_iso3"] == iso3
    assert linhas[1]["ano"] == 2025
    assert linhas[1]["valor"] is None


def test_transformar_rejeita_payload_invalido() -> None:
    with pytest.raises(WorldBankError, match="formato de payload inválido"):
        transformar([])

    with pytest.raises(WorldBankError, match="esperado list"):
        transformar({"erro": "invalido"})  # type: ignore

    with pytest.raises(WorldBankError, match="ano inválido"):
        transformar([{"page": 1}, [{"date": "invalido", "value": 10.0}]])


# --- Testes de Transformação em Formato Largo (Legado / Ingestão) -----------------


def test_transformar_largo_combina_series_e_preserva_ausentes() -> None:
    quadro = transformar_largo(
        _payload_simples(("2024", 5.0), ("2023", 4.5)),
        _payload_simples(("2024", 18_000.0), ("2022", None)),
    )

    assert quadro["ano"].tolist() == [2022, 2023, 2024]
    assert quadro.loc[quadro["ano"] == 2024, "crescimento_pib_pct"].item() == 5.0
    assert quadro.loc[quadro["ano"] == 2024, "pib_usd"].item() == 18_000.0
    assert quadro.loc[quadro["ano"] == 2022, "pib_usd"].isna().item()


def test_transformar_largo_rejeita_payload_invalido() -> None:
    with pytest.raises(WorldBankError):
        transformar_largo([], _payload_simples(("2024", 18_000.0)))

    with pytest.raises(WorldBankError):
        transformar_largo(_payload_simples(("2024", 5.0)), [])


# --- Testes de Checagem e Qualidade de Dados ------------------------------------


def test_checagem_rejeita_duplicidade() -> None:
    linhas = [
        {"indicador": "NY.GDP.MKTP.KD.ZG", "ano": 2020, "valor": 2.2},
        {"indicador": "NY.GDP.MKTP.KD.ZG", "ano": 2020, "valor": 2.2},
    ]
    with pytest.raises(ChecagemError, match="duplicidade"):
        checar(linhas, pais="CHN")


def test_checagem_rejeita_lista_vazia() -> None:
    with pytest.raises(ChecagemError, match="resposta vazia"):
        checar([], pais="CHN")


def test_checagem_rejeita_serie_truncada() -> None:
    linhas = [
        {"indicador": "NY.GDP.MKTP.KD.ZG", "ano": 2000 + i, "valor": 2.0}
        for i in range(20)  # começa em 2000 em vez de <= 1965
    ]
    with pytest.raises(ChecagemError, match="série histórica truncada"):
        checar(linhas, pais="USA")


def test_checagem_rejeita_volume_insuficiente() -> None:
    linhas = [
        {"indicador": "NY.GDP.MKTP.KD.ZG", "ano": 1960 + i * 2, "valor": 2.0}
        for i in range(20)  # começa em 1960, mas só tem 20 anos no total (esperado >= 55)
    ]
    with pytest.raises(ChecagemError, match="volume abaixo do esperado"):
        checar(linhas, pais="USA")


def test_checagem_regras_especificas_russia() -> None:
    # Caso 1: Rússia com volume pós-1990 insuficiente deve falhar
    linhas_sem_pos_1990 = [
        {"indicador": "NY.GDP.MKTP.KD.ZG", "ano": ano, "valor": None}
        for ano in range(1960, 2020)
    ]
    with pytest.raises(ChecagemError, match="volume pós-1990 insuficiente"):
        checar(linhas_sem_pos_1990, pais="RUS")

    # Caso 2: Rússia válida com nulos soviéticos legítimos pré-1990 e dados pós-1990
    linhas_validas_rus = [
        {"indicador": "NY.GDP.MKTP.KD.ZG", "ano": ano, "valor": None}
        for ano in range(1960, 1990)
    ] + [
        {"indicador": "NY.GDP.MKTP.KD.ZG", "ano": ano, "valor": 2.5}
        for ano in range(1990, 2022)
    ]
    # Não deve lançar erro
    checar(linhas_validas_rus, pais="RUS")


# --- Testes de Mapeamento e Nomes de Diretório -----------------------------------


def test_sufixo_e_diretorios_padrao() -> None:
    assert sufixo_pais("CHN") == "china"
    assert sufixo_pais("USA") == "usa"
    assert sufixo_pais("RUS") == "russia"
    assert sufixo_pais("chn") == "china"

    assert diretorio_padrao_pais("CHN").as_posix() == "data/parquet/pib_china"
    assert diretorio_padrao_pais("USA").as_posix() == "data/parquet/pib_usa"
    assert diretorio_padrao_pais("RUS").as_posix() == "data/parquet/pib_russia"

    assert raw_dir_padrao_pais("CHN").as_posix() == "data/raw/pib_china"
    assert raw_dir_padrao_pais("USA").as_posix() == "data/raw/pib_usa"
    assert raw_dir_padrao_pais("RUS").as_posix() == "data/raw/pib_russia"
