"""PIB (SIDRA 1846): transformação e checagens em memória, com respostas reais de 2026-10-13.

A gravação nas tabelas Delta fica em tests/integration/test_pib.py.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from inflatrack.bronze import pib as bronze_pib
from inflatrack.common.bronze import ChecagemError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "pib"


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


def test_codigo_do_setor_fica_texto(nomes, corpo_2026) -> None:
    """Contrato 1.3: código de setor é VARCHAR, nunca número."""
    linhas = bronze_pib.transformar(json.loads(corpo_2026), nomes)
    assert all(isinstance(linha["codigo_setor"], str) for linha in linhas)


def test_marcador_vira_nulo_e_mantem_a_linha(nomes, corpo_2026) -> None:
    payload = json.loads(corpo_2026)
    payload[0]["V"] = "..."
    linha = bronze_pib.transformar(payload, nomes)[0]
    assert linha["valor"] is None
    assert linha["valor_bruto"] == "..."


def test_valor_negativo_nao_e_marcador(nomes, corpo_2026) -> None:
    payload = json.loads(corpo_2026)
    payload[0]["V"] = "-0.67"
    linha = bronze_pib.transformar(payload, nomes)[0]
    assert str(linha["valor"]) == "-0.67"


def test_checar_aceita_ano_corrente_incompleto(nomes, corpo_2026) -> None:
    linhas = bronze_pib.transformar(json.loads(corpo_2026), nomes)
    bronze_pib.checar(linhas, 2026, hoje=date(2026, 10, 13))


def test_checar_recusa_ano_antigo_incompleto(nomes, corpo_2026) -> None:
    linhas = bronze_pib.transformar(json.loads(corpo_2026), nomes)
    with pytest.raises(ChecagemError, match="esperado 4"):
        bronze_pib.checar(linhas, 2026, hoje=date(2028, 1, 1))


def test_checar_recusa_setor_faltando(nomes, corpo_2026) -> None:
    linhas = bronze_pib.transformar(json.loads(corpo_2026)[1:], nomes)
    with pytest.raises(ChecagemError, match="22 setores"):
        bronze_pib.checar(linhas, 2026, hoje=date(2026, 10, 13))


def test_checar_recusa_vazio() -> None:
    with pytest.raises(ChecagemError, match="vazia"):
        bronze_pib.checar([], 2020)


def test_campo_a_mais_e_recusado(nomes, corpo_2026) -> None:
    payload = json.loads(corpo_2026)
    payload[0]["D5C"] = "1"
    with pytest.raises(ChecagemError, match="campos"):
        bronze_pib.transformar(payload, nomes)


def test_coletar_recusa_intervalo_invertido() -> None:
    assert bronze_pib.main(["coletar", "--de", "2026", "--ate", "2025"]) == 1
