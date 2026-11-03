"""Bronze do PIB (SIDRA 1846) gravada em Delta, com respostas reais da API de 2026-10-13.

Transformação e checagens em memória ficam em tests/unit/test_pib.py.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from inflatrack.bronze import pib as bronze_pib
from inflatrack.common import bronze

FIXTURES = Path(__file__).parent.parent / "fixtures" / "pib"
AGORA = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


@pytest.fixture
def nomes() -> dict[str, str]:
    metadados = json.loads((FIXTURES / "1846-metadados.json").read_text(encoding="utf-8"))
    return bronze_pib.nomes_dos_setores(metadados)


@pytest.fixture
def corpo_2026() -> str:
    return (FIXTURES / "1846-2026.json").read_text(encoding="utf-8")


def test_reexecucao_nao_grava_e_revisao_vira_linha_nova(tmp_path, nomes, corpo_2026) -> None:
    resposta = bronze.Resposta(
        bronze_pib.requisicao_do_ano(2026), 200, "application/json", corpo_2026
    )

    primeira = bronze_pib.gravar_anos(tmp_path, [(2026, resposta)], nomes, AGORA)
    segunda = bronze_pib.gravar_anos(tmp_path, [(2026, resposta)], nomes, AGORA)

    payload = json.loads(corpo_2026)
    payload[0]["V"] = str(int(payload[0]["V"]) + 1)
    revisada = bronze.Resposta(resposta.url, 200, "application/json", json.dumps(payload))
    terceira = bronze_pib.gravar_anos(tmp_path, [(2026, revisada)], nomes, AGORA)

    assert (primeira.respostas_novas, primeira.linhas_novas) == (1, 46)
    assert (segunda.respostas_novas, segunda.linhas_novas) == (0, 0)
    assert (terceira.respostas_novas, terceira.linhas_novas) == (1, 1)
    assert bronze.ler(tmp_path, "valor").num_rows == 47


def test_resposta_reprovada_nao_grava_nada(tmp_path, nomes, corpo_2026) -> None:
    payload = json.loads(corpo_2026)[1:]
    resposta = bronze.Resposta("u", 200, None, json.dumps(payload))
    with pytest.raises(bronze.ChecagemError):
        bronze_pib.gravar_anos(tmp_path, [(2026, resposta)], nomes, AGORA)
    assert bronze.versao(tmp_path, "resposta") is None
