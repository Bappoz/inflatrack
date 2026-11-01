"""Testes da camada Bronze do Dólar Comercial (Delta Lake)."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from deltalake import DeltaTable
from inflatrack.dolar_olinda import OlindaError

from inflatrack import bronze_dolar
from inflatrack.bronze import dolar

FIXTURE_DOLAR = Path(__file__).parent.parent / "fixtures" / "dolar" / "olinda_amostra.json"


@pytest.fixture
def payload_dolar() -> dict:
    return json.loads(FIXTURE_DOLAR.read_text(encoding="utf-8"))


def test_transformar_dolar_preserva_todos_os_boletins(payload_dolar: dict) -> None:
    linhas = bronze_dolar.transformar(payload_dolar)
    assert len(linhas) == 4

    tipos = [item["tipo_boletim"] for item in linhas]
    assert tipos == ["Abertura", "Intermediário", "Fechamento PTAX", "Fechamento PTAX"]

    primeiro = linhas[0]
    assert primeiro["cotacao_compra"] == 4.0207
    assert primeiro["cotacao_venda"] == 4.0213
    assert primeiro["ano"] == 2020
    assert primeiro["data_referencia"].isoformat() == "2020-01-02"


def test_transformar_dolar_invalido() -> None:
    with pytest.raises(OlindaError):
        bronze_dolar.transformar({"value": []})

    with pytest.raises(OlindaError):
        bronze_dolar.transformar({"value": [{"cotacaoCompra": 4.0}]})


def test_checar_dolar_valido(payload_dolar: dict) -> None:
    linhas = bronze_dolar.transformar(payload_dolar)
    bronze_dolar.checar(linhas)


def test_checar_dolar_invalido() -> None:
    with pytest.raises(bronze_dolar.ChecagemError, match="não positiva"):
        bronze_dolar.checar(
            [
                {
                    "data_hora_cotacao": datetime(2020, 1, 2, 10, 0, tzinfo=UTC),
                    "data_referencia": datetime(2020, 1, 2).date(),
                    "cotacao_compra": -1.0,
                    "cotacao_venda": 4.0,
                    "tipo_boletim": "Abertura",
                    "ano": 2020,
                }
            ]
        )

    with pytest.raises(bronze_dolar.ChecagemError, match="spread negativo"):
        bronze_dolar.checar(
            [
                {
                    "data_hora_cotacao": datetime(2020, 1, 2, 10, 0, tzinfo=UTC),
                    "data_referencia": datetime(2020, 1, 2).date(),
                    "cotacao_compra": 4.50,
                    "cotacao_venda": 4.00,
                    "tipo_boletim": "Abertura",
                    "ano": 2020,
                }
            ]
        )


def test_gravar_e_idempotencia_dolar(tmp_path: Path, payload_dolar: dict) -> None:
    corpo = json.dumps(payload_dolar, ensure_ascii=False)
    requisicao = "CotacaoDolarPeriodo_teste"

    # Primeira gravação
    res1 = bronze_dolar.gravar(tmp_path, requisicao=requisicao, corpo=corpo)
    assert res1.resposta_nova is True
    assert res1.linhas_lidas == 4
    assert res1.linhas_novas == 4

    # Tabelas Delta criadas
    dt_resp = DeltaTable(str(tmp_path / "resposta"))
    dt_bol = DeltaTable(str(tmp_path / "boletim"))
    assert dt_resp.to_pyarrow_table().num_rows == 1
    assert dt_bol.to_pyarrow_table().num_rows == 4

    # Segunda gravação (reexecução exata)
    res2 = bronze_dolar.gravar(tmp_path, requisicao=requisicao, corpo=corpo)
    assert res2.resposta_nova is False
    assert res2.linhas_lidas == 4
    assert res2.linhas_novas == 0

    # Contagens permanecem inalteradas
    assert DeltaTable(str(tmp_path / "resposta")).to_pyarrow_table().num_rows == 1
    assert DeltaTable(str(tmp_path / "boletim")).to_pyarrow_table().num_rows == 4


def test_importar_raw_legado_dolar(tmp_path: Path, payload_dolar: dict) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    arquivo_gzip = raw_dir / "dolar_2020.json.gz"
    with gzip.open(arquivo_gzip, "wt", encoding="utf-8") as f:
        json.dump(payload_dolar, f)

    destino_delta = tmp_path / "delta"
    total1 = dolar.importar(raw_dir, destino=destino_delta)
    assert total1 == 4

    # Reimportar o mesmo arquivo deve ser estritamente idempotente (0 novas)
    total2 = dolar.importar(raw_dir, destino=destino_delta)
    assert total2 == 0


def test_checar_tabela_dolar(tmp_path: Path, payload_dolar: dict) -> None:
    destino_delta = tmp_path / "delta"

    # Diretório vazio sem tabelas Delta deve falhar
    with pytest.raises(dolar.ChecagemError, match="não encontrada"):
        dolar.checar_tabela(destino_delta)

    # Grava dados válidos e checa sucesso
    corpo = json.dumps(payload_dolar, ensure_ascii=False)
    dolar.gravar(destino_delta, requisicao="teste:checar", corpo=corpo)
    dolar.checar_tabela(destino_delta)
