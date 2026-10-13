"""Bronze do PIB (SIDRA 1846), com respostas reais da API de 2026-10-13."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from inflatrack import bronze, bronze_pib

FIXTURES = Path(__file__).parent / "fixtures" / "pib"
AGORA = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


@pytest.fixture
def nomes() -> dict[str, str]:
    metadados = json.loads((FIXTURES / "1846-metadados.json").read_text(encoding="utf-8"))
    return bronze_pib.nomes_dos_setores(metadados)


@pytest.fixture
def corpo_2026() -> str:
    return (FIXTURES / "1846-2026.json").read_text(encoding="utf-8")


def test_transformar_mantem_todos_os_campos(nomes, corpo_2026) -> None:
    linhas = bronze_pib.transformar(json.loads(corpo_2026), nomes)

    assert len(linhas) == 46  # 2026: dois trimestres x 23 setores
    pib_t1 = next(
        linha
        for linha in linhas
        if linha["codigo_setor"] == "90707" and linha["data_referencia"] == date(2026, 1, 1)
    )
    assert pib_t1["nome_setor"] == "PIB a preços de mercado"
    assert pib_t1["codigo_variavel"] == 585
    assert pib_t1["codigo_unidade"] == 1550
    assert str(pib_t1["valor"]) == pib_t1["valor_bruto"]


def test_marcador_vira_nulo_e_mantem_a_linha(nomes, corpo_2026) -> None:
    payload = json.loads(corpo_2026)
    payload[0]["V"] = "..."
    linha = bronze_pib.transformar(payload, nomes)[0]
    assert linha["valor"] is None
    assert linha["valor_bruto"] == "..."


def test_checar_aceita_ano_corrente_incompleto(nomes, corpo_2026) -> None:
    linhas = bronze_pib.transformar(json.loads(corpo_2026), nomes)
    bronze_pib.checar(linhas, 2026, hoje=date(2026, 10, 13))


def test_checar_recusa_ano_antigo_incompleto(nomes, corpo_2026) -> None:
    linhas = bronze_pib.transformar(json.loads(corpo_2026), nomes)
    with pytest.raises(bronze.ChecagemError, match="esperado 4"):
        bronze_pib.checar(linhas, 2026, hoje=date(2028, 1, 1))


def test_checar_recusa_setor_faltando(nomes, corpo_2026) -> None:
    linhas = bronze_pib.transformar(json.loads(corpo_2026)[1:], nomes)
    with pytest.raises(bronze.ChecagemError, match="22 setores"):
        bronze_pib.checar(linhas, 2026, hoje=date(2026, 10, 13))


def test_checar_recusa_vazio() -> None:
    with pytest.raises(bronze.ChecagemError, match="vazia"):
        bronze_pib.checar([], 2020)


def test_campo_a_mais_e_recusado(nomes, corpo_2026) -> None:
    payload = json.loads(corpo_2026)
    payload[0]["D5C"] = "1"
    with pytest.raises(bronze.ChecagemError, match="campos"):
        bronze_pib.transformar(payload, nomes)


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
