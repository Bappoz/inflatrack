from datetime import date
from decimal import Decimal

from inflatrack.reverse_etl.publicar_site import (
    PRACAS_IPCA,
    UF_PRACA,
    linhas_json,
    perguntas_do_painel,
)

UFS = {
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
}


def test_toda_uf_tem_uma_praca_do_ipca() -> None:
    assert set(UF_PRACA) == UFS
    assert set(UF_PRACA.values()) <= PRACAS_IPCA
    assert UF_PRACA["DF"] == 5300108
    assert UF_PRACA["SP"] == 3501
    assert UF_PRACA["TO"] == 1  # sem praça no IPCA: Brasil


def test_linhas_json_converte_data_e_decimal() -> None:
    linhas = linhas_json([{"mes": date(2026, 10, 1), "pct": Decimal("4.56"), "nome": "x"}])

    assert linhas == [{"mes": "2026-10-01", "pct": 4.56, "nome": "x"}]


def test_painel_traz_so_o_painel_do_lojista_sem_o_reajuste_por_produto() -> None:
    perguntas = perguntas_do_painel()
    arquivos = [p["arquivo"] for p in perguntas]

    assert len(perguntas) == 6
    assert "p5_reajuste_minimo_por_produto.sql" not in arquivos
    assert not any(a.startswith("clima_") for a in arquivos)
    assert all({"id", "titulo", "grafico", "eixo_x", "eixo_y"} <= set(p) for p in perguntas)
