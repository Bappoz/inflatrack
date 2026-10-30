"""Bronze das commodities, com recortes de respostas reais da Alpha Vantage (2026-10-13)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from inflatrack.alphavantage import AlphaVantageClient

from inflatrack import bronze, ingest_commodities

FIXTURES = Path(__file__).parent.parent / "fixtures" / "commodities"
AGORA = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def volume_do_recorte(monkeypatch: pytest.MonkeyPatch) -> None:
    """Os recortes têm poucas linhas; o mínimo real é testado na evidência."""
    monkeypatch.setattr(ingest_commodities, "LINHAS_MINIMAS", dict.fromkeys(["WTI", "CORN"], 1))


def _corpo(nome: str) -> str:
    return (FIXTURES / f"{nome}-recorte.json").read_text(encoding="utf-8")


def _resposta(symbol: str, corpo: str) -> bronze.Resposta:
    intervalo = ingest_commodities.COMMODITY_CONFIGS[symbol]["interval"]
    return bronze.Resposta(
        AlphaVantageClient.url_publica(symbol, intervalo), 200, "application/json", corpo
    )


def test_transformar_mantem_ponto_como_preco_nulo() -> None:
    linhas = ingest_commodities.transformar("CORN", json.loads(_corpo("corn")))

    assert len(linhas) == 7
    ausentes = [linha for linha in linhas if linha["preco"] is None]
    assert len(ausentes) == 2
    assert {linha["unidade"] for linha in linhas} == {"dollar per metric ton"}
    assert linhas[0]["intervalo"] == "monthly"


def test_preco_negativo_do_wti_e_mantido() -> None:
    """Abril de 2020: o WTI fechou negativo. Descartar ≤ 0 é regra do dbt."""
    linhas = ingest_commodities.transformar("WTI", json.loads(_corpo("wti")))
    negativo = next(linha for linha in linhas if linha["data_referencia"] == date(2020, 4, 20))
    assert negativo["preco"] < 0


@pytest.mark.parametrize(
    "corpo",
    [
        {"Information": "We have detected your API key ... 25 requests per day."},
        {"Error Message": "Invalid API call."},
        {"name": "x", "interval": "monthly", "unit": "u"},
        {"name": "x", "interval": "monthly", "unit": "u", "data": []},
        {
            "name": "x",
            "interval": "daily",
            "unit": "u",
            "data": [{"date": "2026-01-01", "value": "1"}],
        },
    ],
    ids=["cota-esgotada", "erro", "sem-data", "lista-vazia", "intervalo-errado"],
)
def test_resposta_sem_serie_falha_e_nao_grava(tmp_path: Path, corpo: dict) -> None:
    with pytest.raises(bronze.ChecagemError):
        ingest_commodities.gravar(tmp_path, "CORN", _resposta("CORN", json.dumps(corpo)))
    assert bronze.versao(tmp_path, "resposta") is None


def test_volume_abaixo_do_minimo_falha(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(ingest_commodities.LINHAS_MINIMAS, "CORN", 559)
    with pytest.raises(bronze.ChecagemError, match="mínimo 559"):
        ingest_commodities.gravar(tmp_path, "CORN", _resposta("CORN", _corpo("corn")))


def test_reexecucao_nao_grava_e_serie_nova_substitui_a_particao(tmp_path: Path) -> None:
    ingest_commodities.gravar(tmp_path, "WTI", _resposta("WTI", _corpo("wti")), AGORA)
    primeira = ingest_commodities.gravar(tmp_path, "CORN", _resposta("CORN", _corpo("corn")))
    versao = bronze.versao(tmp_path, "cotacao")

    segunda = ingest_commodities.gravar(tmp_path, "CORN", _resposta("CORN", _corpo("corn")))
    assert (segunda.resposta_nova, segunda.particao_substituida) == (False, False)
    assert bronze.versao(tmp_path, "cotacao") == versao

    dados = json.loads(_corpo("corn"))
    dados["data"] = dados["data"][:3]
    terceira = ingest_commodities.gravar(tmp_path, "CORN", _resposta("CORN", json.dumps(dados)))

    assert primeira.resposta_nova and terceira.particao_substituida
    simbolos = bronze.ler(tmp_path, "cotacao").column("symbol").to_pylist()
    assert (simbolos.count("CORN"), simbolos.count("WTI")) == (3, 8)
    assert bronze.ler(tmp_path, "resposta").num_rows == 3


def test_requisicao_guardada_nao_tem_a_chave() -> None:
    url = AlphaVantageClient.url_publica("WTI", "daily")
    assert "apikey" not in url
    assert url.endswith("function=WTI&interval=daily")


def test_cota_esgotada_interrompe_e_sai_com_erro(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pedidos = []

    class ClienteSemCota:
        def buscar_resposta(self, function: str, interval: str) -> bronze.Resposta:
            pedidos.append(function)
            return _resposta(function, json.dumps({"Information": "rate limit"}))

    monkeypatch.setattr(ingest_commodities, "AlphaVantageClient", ClienteSemCota)
    codigo = ingest_commodities.main(["--parquet-dir", str(tmp_path), "--commodity", "ALL"])

    assert codigo == 1
    assert pedidos == ["WTI"]
    assert bronze.versao(tmp_path, "resposta") is None


def test_sem_chave_falha_antes_de_pedir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("inflatrack.alphavantage.ALPHAVANTAGE_API_KEY", None)
    monkeypatch.setattr(AlphaVantageClient, "buscar_resposta", lambda *_: pytest.fail("pediu"))
    assert ingest_commodities.main(["--parquet-dir", str(tmp_path)]) == 1
