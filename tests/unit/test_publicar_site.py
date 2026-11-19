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


def test_so_vao_para_o_site_os_graficos_permitidos() -> None:
    from inflatrack.reverse_etl.publicar_site import PAINEL_DO_SITE

    assert {p["id"] for p in perguntas_do_painel()} == set(PAINEL_DO_SITE)


def test_grafico_com_coluna_de_preco_e_barrado() -> None:
    import pytest

    from inflatrack.reverse_etl.publicar_site import conferir_sem_preco

    with pytest.raises(ValueError, match="preco_novo"):
        conferir_sem_preco("p9", [{"produto": "Arroz", "preco_novo": 25.0}])
    conferir_sem_preco("p1", [{"setor": "Alimentação", "inflacao_12m_pct": 4.5}])


def test_conexao_com_o_supabase_desliga_comandos_preparados(monkeypatch) -> None:
    """O Transaction pooler do Supabase não aguenta comando preparado entre conexões."""
    from inflatrack.reverse_etl import publicar_site

    vistos = {}

    class Parar(Exception):
        pass

    def conectar(dsn, **kwargs):
        vistos.update(kwargs)
        raise Parar

    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://x@y:6543/z")
    monkeypatch.setattr(publicar_site, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(publicar_site, "coletar", lambda *a, **k: None)
    monkeypatch.setattr(publicar_site.psycopg, "connect", conectar)

    import pytest

    with pytest.raises(Parar):
        publicar_site.main([])
    assert "prepare_threshold" in vistos
    assert vistos["prepare_threshold"] is None
