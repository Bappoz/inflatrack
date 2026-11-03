import gzip
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from deltalake import DeltaTable

from inflatrack.bronze import pib_internacional
from inflatrack.bronze.pib_internacional import (
    ChecagemError,
    checar_tabelas_pais,
    coletar_pais,
    gravar,
    importar_raw_pais,
)
from inflatrack.clients.worldbank import WorldBankClient
from inflatrack.common.bronze import Resposta


def _gerar_corpo_simulado(pais_iso3: str, pais_nome: str, valor_base: float = 3.0) -> str:
    """Gera um payload JSON com 60 anos (1961 a 2020) para validar regras de volume."""
    anos_extras = [
        f'{{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}}, '
        f'"country": {{"id": "{pais_iso3[:2]}", "value": "{pais_nome}"}}, '
        f'"countryiso3code": "{pais_iso3}", "date": "{ano}", "value": {valor_base}}}'
        for ano in range(1962, 2020)
    ]
    return f"""[
        {{"page": 1, "pages": 1, "per_page": 1000, "total": {len(anos_extras) + 2}}},
        [
            {{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}},
              "country": {{"id": "{pais_iso3[:2]}", "value": "{pais_nome}"}},
              "countryiso3code": "{pais_iso3}", "date": "1961", "value": {valor_base}}},
            {",".join(anos_extras)},
            {{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}},
              "country": {{"id": "{pais_iso3[:2]}", "value": "{pais_nome}"}},
              "countryiso3code": "{pais_iso3}", "date": "2020", "value": {valor_base}}}
        ]
    ]"""


def _gerar_corpo_russia() -> str:
    """Gera payload da Rússia com nulos pré-1990 e valores pós-1990."""
    anos_pre_1990 = [
        f'{{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}}, '
        f'"country": {{"id": "RU", "value": "Russian Federation"}}, '
        f'"countryiso3code": "RUS", "date": "{ano}", "value": null}}'
        for ano in range(1960, 1990)
    ]
    anos_pos_1990 = [
        f'{{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}}, '
        f'"country": {{"id": "RU", "value": "Russian Federation"}}, '
        f'"countryiso3code": "RUS", "date": "{ano}", "value": 2.5}}'
        for ano in range(1990, 2020)
    ]
    todos = anos_pre_1990 + anos_pos_1990
    return f"""[
        {{"page": 1, "pages": 1, "per_page": 1000, "total": {len(todos)}}},
        [{",".join(todos)}]
    ]"""


@pytest.mark.parametrize(
    ("pais", "corpo"),
    [
        ("CHN", _gerar_corpo_simulado("CHN", "China", 5.2)),
        ("USA", _gerar_corpo_simulado("USA", "United States", 2.5)),
        ("RUS", _gerar_corpo_russia()),
    ],
)
def test_gravar_idempotente_delta_por_pais(tmp_path: Path, pais: str, corpo: str) -> None:
    destino = tmp_path / f"pib_{pais.lower()}"

    # 1ª execução: dados são inseridos
    gravacao1 = gravar(
        destino=destino,
        indicador="NY.GDP.MKTP.KD.ZG",
        requisicao=f"https://api.worldbank.org/test/{pais}",
        corpo=corpo,
        pais=pais,
    )
    assert gravacao1.resposta_nova is True
    assert gravacao1.linhas_novas == 60
    assert DeltaTable.is_deltatable(str(destino / "resposta"))
    assert DeltaTable.is_deltatable(str(destino / "indicador"))

    # 2ª execução com mesmo corpo: resposta não é regravada e observações novas são 0
    gravacao2 = gravar(
        destino=destino,
        indicador="NY.GDP.MKTP.KD.ZG",
        requisicao=f"https://api.worldbank.org/test/{pais}",
        corpo=corpo,
        pais=pais,
    )
    assert gravacao2.resposta_nova is False
    assert gravacao2.linhas_novas == 0


def test_checar_tabelas_pais_valida_e_detecta_erros(tmp_path: Path) -> None:
    destino = tmp_path / "pib_china"

    # Tabela inexistente deve falhar
    with pytest.raises(ChecagemError, match="não existe"):
        checar_tabelas_pais("CHN", destino=destino)

    # Grava dados válidos
    corpo = _gerar_corpo_simulado("CHN", "China", 5.0)
    gravar(
        destino=destino,
        indicador="NY.GDP.MKTP.KD.ZG",
        requisicao="https://api.worldbank.org/test/CHN",
        corpo=corpo,
        pais="CHN",
    )

    # Checagem deve passar sem erros
    checar_tabelas_pais("CHN", destino=destino)


def test_importar_raw_pais_grava_em_delta(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    destino = tmp_path / "delta"
    raw_dir.mkdir(parents=True)

    # Cria arquivo .json.gz simulando extração bruta
    arquivo_raw = raw_dir / "NY.GDP.MKTP.KD.ZG.json.gz"
    corpo_obj = json.loads(_gerar_corpo_simulado("USA", "United States", 2.2))
    with gzip.open(arquivo_raw, "wt", encoding="utf-8") as f:
        json.dump(corpo_obj, f)

    total_novas = importar_raw_pais("USA", raw_dir=raw_dir, destino=destino)
    assert total_novas == 60
    assert DeltaTable.is_deltatable(str(destino / "indicador"))


def test_coletar_pais_com_cliente_mock(tmp_path: Path) -> None:
    cliente_mock = MagicMock(spec=WorldBankClient)

    def _buscar(pais: str, indicador: str) -> Resposta:
        valor = 5.0 if "KD" in indicador else 1000.0
        corpo = _gerar_corpo_simulado(pais, "China", valor_base=valor)
        return Resposta(
            url=f"https://api.worldbank.org/{pais}/{indicador}",
            status_http=200,
            tipo_conteudo="application/json",
            corpo=corpo,
        )

    cliente_mock.buscar_resposta.side_effect = _buscar

    resultados = coletar_pais("CHN", destino=tmp_path, cliente=cliente_mock)
    assert len(resultados) == len(pib_internacional.INDICADORES)
    for res in resultados:
        assert res.resposta_nova is True
        assert res.linhas_novas == 60
