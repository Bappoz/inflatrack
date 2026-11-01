"""Testes da camada Bronze da Taxa Selic (Delta Lake)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from deltalake import DeltaTable
from inflatrack.selic_sgs import SGSError

from inflatrack import bronze_selic
from inflatrack.bronze import selic

FIXTURE_SELIC = Path(__file__).parent.parent / "fixtures" / "selic" / "sgs_amostra.json"


@pytest.fixture
def payload_selic() -> list[dict]:
    return json.loads(FIXTURE_SELIC.read_text(encoding="utf-8"))


def test_transformar_selic_sem_interpolacao(payload_selic: list[dict]) -> None:
    linhas = bronze_selic.transformar(payload_selic)
    assert len(linhas) == 3

    # Preserva estritamente os dias da API, sem interpolar sábados e domingos
    datas = [item["data_referencia"].isoformat() for item in linhas]
    assert datas == ["2020-01-02", "2020-01-03", "2020-01-06"]

    primeiro = linhas[0]
    assert primeiro["taxa_dia_pct"] == pytest.approx(0.017089)
    assert primeiro["ano"] == 2020


def test_transformar_selic_invalido() -> None:
    with pytest.raises(SGSError):
        bronze_selic.transformar([])

    with pytest.raises(SGSError):
        bronze_selic.transformar([{"data": "02/01/2020"}])


def test_checar_selic_valida(payload_selic: list[dict]) -> None:
    linhas = bronze_selic.transformar(payload_selic)
    bronze_selic.checar(linhas)


def test_checar_selic_fora_de_faixa() -> None:
    # Taxa anualizada passada por engano (> 1.0% ao dia)
    with pytest.raises(bronze_selic.ChecagemError, match="fora da faixa"):
        bronze_selic.checar(
            [
                {
                    "data_referencia": Path("2020-01-02"),
                    "taxa_dia_pct": 13.75,
                    "ano": 2020,
                }
            ]
        )

    # Taxa negativa
    with pytest.raises(bronze_selic.ChecagemError, match="fora da faixa"):
        bronze_selic.checar(
            [
                {
                    "data_referencia": Path("2020-01-02"),
                    "taxa_dia_pct": -0.05,
                    "ano": 2020,
                }
            ]
        )


def test_gravar_e_idempotencia_selic(tmp_path: Path, payload_selic: list[dict]) -> None:
    corpo = json.dumps(payload_selic, ensure_ascii=False)
    requisicao = "bcdata.sgs.11_teste"

    # Primeira gravação
    res1 = selic.gravar(tmp_path, requisicao=requisicao, corpo=corpo)
    assert res1.resposta_nova is True
    assert res1.linhas_lidas == 3
    assert res1.linhas_novas == 3

    # Tabelas Delta criadas
    dt_resp = DeltaTable(str(tmp_path / "resposta"))
    dt_taxa = DeltaTable(str(tmp_path / "taxa_dia"))
    assert dt_resp.to_pyarrow_table().num_rows == 1
    assert dt_taxa.to_pyarrow_table().num_rows == 3

    # Segunda gravação (reexecução exata)
    res2 = selic.gravar(tmp_path, requisicao=requisicao, corpo=corpo)
    assert res2.resposta_nova is False
    assert res2.linhas_lidas == 3
    assert res2.linhas_novas == 0

    # Contagens inalteradas
    assert DeltaTable(str(tmp_path / "resposta")).to_pyarrow_table().num_rows == 1
    assert DeltaTable(str(tmp_path / "taxa_dia")).to_pyarrow_table().num_rows == 3


def test_importar_raw_legado_selic(tmp_path: Path, payload_selic: list[dict]) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    arquivo_gzip = raw_dir / "selic_2020.json.gz"
    with gzip.open(arquivo_gzip, "wt", encoding="utf-8") as f:
        json.dump(payload_selic, f)

    destino_delta = tmp_path / "delta"
    total1 = selic.importar(raw_dir, destino=destino_delta)
    assert total1 == 3

    # Reimportar o mesmo arquivo deve ser estritamente idempotente (0 novas)
    total2 = selic.importar(raw_dir, destino=destino_delta)
    assert total2 == 0


def test_checar_tabela_selic(tmp_path: Path, payload_selic: list[dict]) -> None:
    destino_delta = tmp_path / "delta"

    # Diretório vazio sem tabelas Delta deve falhar
    with pytest.raises(selic.ChecagemError, match="não encontrada"):
        selic.checar_tabela(destino_delta)

    # Grava dados válidos e checa sucesso
    corpo = json.dumps(payload_selic, ensure_ascii=False)
    selic.gravar(destino_delta, requisicao="teste:checar", corpo=corpo)
    selic.checar_tabela(destino_delta)
