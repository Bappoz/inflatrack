from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from inflatrack import ingest_clima


def test_medicoes_automaticas_usam_mapeamento_e_sete_dias_completos():
    with (
        patch.object(ingest_clima, "datetime") as relogio,
        patch.object(ingest_clima, "processar_estacoes"),
        patch.object(ingest_clima, "processar_medicoes", return_value=(0, 0)) as coletar,
    ):
        relogio.now.return_value = datetime(2027, 1, 3, 0, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))
        assert ingest_clima.main(["--medicoes"]) == 0
    estacoes = coletar.call_args.args[1]
    assert len(estacoes) == 15
    assert len(set(estacoes)) == 15
    assert set(estacoes) == set(ingest_clima.estacoes_mapeadas())
    assert coletar.call_args.args[2:] == ("2026-12-27", "2027-01-02")
    relogio.now.assert_called_once_with(ZoneInfo("America/Sao_Paulo"))


def test_medicoes_preservam_estacoes_e_intervalo_explicitos():
    with (
        patch.object(ingest_clima, "processar_estacoes"),
        patch.object(ingest_clima, "processar_medicoes", return_value=(1, 1)) as coletar,
    ):
        assert (
            ingest_clima.main(
                [
                    "--medicoes",
                    "--estacao",
                    "A001",
                    "--de",
                    "2026-10-01",
                    "--ate",
                    "2026-10-02",
                ]
            )
            == 0
        )
    assert coletar.call_args.args[1:] == (["A001"], "2026-10-01", "2026-10-02")


@pytest.mark.parametrize(
    "argumentos",
    [
        ["--medicoes", "--de", "2026-10-01"],
        ["--medicoes", "--ate", "2026-10-01"],
        ["--medicoes", "--de", "2026-10-02", "--ate", "2026-10-01"],
        ["--apenas-estacoes", "--medicoes"],
    ],
)
def test_config_invalida_falha_antes_da_rede(argumentos):
    with (
        patch.object(ingest_clima, "processar_estacoes") as catalogo,
        pytest.raises(SystemExit) as erro,
    ):
        ingest_clima.main(argumentos)
    assert erro.value.code == 2
    catalogo.assert_not_called()


def test_apenas_estacoes_nao_coleta_medicoes():
    with (
        patch.object(ingest_clima, "processar_estacoes") as catalogo,
        patch.object(ingest_clima, "processar_medicoes") as coletar,
    ):
        assert ingest_clima.main(["--apenas-estacoes"]) == 0
    catalogo.assert_called_once()
    coletar.assert_not_called()


def test_mapeamento_vazio_falha_explicitamente(tmp_path, monkeypatch, caplog):
    caminho = tmp_path / "estacoes.csv"
    caminho.write_text("estacao_id,codigo_localidade\n", encoding="utf-8")
    monkeypatch.setattr(ingest_clima, "MAPEAMENTO_ESTACOES", caminho)
    with patch.object(ingest_clima, "processar_estacoes") as catalogo:
        assert ingest_clima.main(["--medicoes"]) == 1
    catalogo.assert_not_called()
    assert "Mapeamento de estações vazio ou inválido" in caplog.text
