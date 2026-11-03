from pathlib import Path

import duckdb
import pytest

from inflatrack.bronze import pib_internacional
from inflatrack.loaders import load_pib_internacional


def _criar_dados_delta(destino: Path, pais: str, valor: float = 3.0) -> None:
    """Cria tabela Delta de indicador para teste de carga."""
    anos_extras = [
        f'{{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}}, '
        f'"country": {{"id": "{pais[:2]}", "value": "{pais}"}}, '
        f'"countryiso3code": "{pais}", "date": "{ano}", "value": {valor}}}'
        for ano in range(1962, 2020)
    ]
    corpo = f"""[
        {{"page": 1, "pages": 1, "per_page": 1000, "total": {len(anos_extras) + 2}}},
        [
            {{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}},
              "country": {{"id": "{pais[:2]}", "value": "{pais}"}},
              "countryiso3code": "{pais}", "date": "1961", "value": {valor}}},
            {",".join(anos_extras)},
            {{"indicator": {{"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth"}},
              "country": {{"id": "{pais[:2]}", "value": "{pais}"}},
              "countryiso3code": "{pais}", "date": "2020", "value": {valor}}}
        ]
    ]"""
    pib_internacional.gravar(
        destino=destino,
        indicador="NY.GDP.MKTP.KD.ZG",
        requisicao=f"https://api.worldbank.org/{pais}",
        corpo=corpo,
        pais=pais,
    )


def test_carregar_pais_cria_schema_e_idempotencia(tmp_path: Path) -> None:
    delta_dir = tmp_path / "pib_china"
    _criar_dados_delta(delta_dir, "CHN", valor=5.2)

    db_path = tmp_path / "teste.duckdb"
    with duckdb.connect(str(db_path)) as conexao:
        novas1 = load_pib_internacional.carregar_pais(conexao, "CHN", delta_dir=delta_dir)
        assert novas1 == 60

        # Verifica schema e existência da tabela
        total1 = conexao.execute("SELECT count(*) FROM bronze.pib_china_indicador").fetchone()[0]
        assert total1 == 60

        # Segunda carga: idempotência (0 novas inserções)
        novas2 = load_pib_internacional.carregar_pais(conexao, "CHN", delta_dir=delta_dir)
        assert novas2 == 0
        total2 = conexao.execute("SELECT count(*) FROM bronze.pib_china_indicador").fetchone()[0]
        assert total2 == 60


def test_carregar_unificado_agrega_todos_os_paises(tmp_path: Path) -> None:
    parquet_base = tmp_path / "parquet"
    _criar_dados_delta(parquet_base / "pib_china", "CHN", valor=5.0)
    _criar_dados_delta(parquet_base / "pib_usa", "USA", valor=2.5)
    _criar_dados_delta(parquet_base / "pib_russia", "RUS", valor=3.0)

    db_path = tmp_path / "unificado.duckdb"
    with duckdb.connect(str(db_path)) as conexao:
        novas1 = load_pib_internacional.carregar_unificado(conexao, parquet_base=parquet_base)
        assert novas1 == 180  # 60 linhas por país x 3 países

        paises_presentes = [
            row[0]
            for row in conexao.execute(
                "SELECT DISTINCT pais_iso3 FROM bronze.pib_internacional_indicador "
                "ORDER BY pais_iso3"
            ).fetchall()
        ]
        assert paises_presentes == ["CHN", "RUS", "USA"]

        # Segunda carga unificada não duplica registros
        novas2 = load_pib_internacional.carregar_unificado(conexao, parquet_base=parquet_base)
        assert novas2 == 0


def test_carregar_delta_inexistente_lanca_erro(tmp_path: Path) -> None:
    db_path = tmp_path / "erro.duckdb"
    with (
        duckdb.connect(str(db_path)) as conexao,
        pytest.raises(FileNotFoundError, match="Tabela Delta não encontrada"),
    ):
        load_pib_internacional.carregar_pais(conexao, "CHN", delta_dir=tmp_path / "inexistente")
