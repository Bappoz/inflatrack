from pathlib import Path

import duckdb
import pytest

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
