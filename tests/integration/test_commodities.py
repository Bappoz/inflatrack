"""Bronze das commodities gravada em Delta, com recortes reais da Alpha Vantage (2026-10-13).

Validação e transformação em memória ficam em tests/unit/test_commodities.py.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from inflatrack.bronze import commodities
from inflatrack.clients.alphavantage import AlphaVantageClient
from inflatrack.common import bronze

FIXTURES = Path(__file__).parent.parent / "fixtures" / "commodities"
AGORA = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def volume_do_recorte(monkeypatch: pytest.MonkeyPatch) -> None:
    """Os recortes têm poucas linhas; o mínimo real é testado na evidência."""
    monkeypatch.setattr(commodities, "LINHAS_MINIMAS", dict.fromkeys(["WTI", "CORN"], 1))


def _corpo(nome: str) -> str:
    return (FIXTURES / f"{nome}-recorte.json").read_text(encoding="utf-8")


def _resposta(symbol: str, corpo: str) -> bronze.Resposta:
    intervalo = commodities.COMMODITY_CONFIGS[symbol]["interval"]
    return bronze.Resposta(
        AlphaVantageClient.url_publica(symbol, intervalo), 200, "application/json", corpo
    )


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
        commodities.gravar(tmp_path, "CORN", _resposta("CORN", json.dumps(corpo)))
    assert bronze.versao(tmp_path, "resposta") is None


def test_volume_abaixo_do_minimo_falha(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(commodities.LINHAS_MINIMAS, "CORN", 559)
    with pytest.raises(bronze.ChecagemError, match="mínimo 559"):
        commodities.gravar(tmp_path, "CORN", _resposta("CORN", _corpo("corn")))


def test_reexecucao_nao_grava_e_serie_nova_substitui_a_particao(tmp_path: Path) -> None:
    commodities.gravar(tmp_path, "WTI", _resposta("WTI", _corpo("wti")), AGORA)
    primeira = commodities.gravar(tmp_path, "CORN", _resposta("CORN", _corpo("corn")))
    versao = bronze.versao(tmp_path, "cotacao")

    segunda = commodities.gravar(tmp_path, "CORN", _resposta("CORN", _corpo("corn")))
    assert (segunda.resposta_nova, segunda.particao_substituida) == (False, False)
    assert bronze.versao(tmp_path, "cotacao") == versao

    dados = json.loads(_corpo("corn"))
    dados["data"] = dados["data"][:3]
    terceira = commodities.gravar(tmp_path, "CORN", _resposta("CORN", json.dumps(dados)))

    assert primeira.resposta_nova and terceira.particao_substituida
    simbolos = bronze.ler(tmp_path, "cotacao").column("symbol").to_pylist()
    assert (simbolos.count("CORN"), simbolos.count("WTI")) == (3, 8)
    assert bronze.ler(tmp_path, "resposta").num_rows == 3


def test_cota_esgotada_interrompe_e_sai_com_erro(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pedidos = []

    class ClienteSemCota:
        def buscar_resposta(self, function: str, interval: str) -> bronze.Resposta:
            pedidos.append(function)
            return _resposta(function, json.dumps({"Information": "rate limit"}))

    monkeypatch.setattr(commodities, "AlphaVantageClient", ClienteSemCota)
    codigo = commodities.main(["--parquet-dir", str(tmp_path), "--commodity", "ALL"])

    assert codigo == 1
    assert pedidos == ["WTI"]
    assert bronze.versao(tmp_path, "resposta") is None


def test_sem_chave_falha_antes_de_pedir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("inflatrack.clients.alphavantage.ALPHAVANTAGE_API_KEY", None)
    monkeypatch.setattr(AlphaVantageClient, "buscar_resposta", lambda *_: pytest.fail("pediu"))
    assert commodities.main(["--parquet-dir", str(tmp_path)]) == 1
