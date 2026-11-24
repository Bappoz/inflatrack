"""Leitura do que o pipeline publicou no Supabase: dashboard por praça e previsão por produto."""

from datetime import date

import pytest

from web.backend import publicacao

DASHBOARD = {
    "latest_month": "2026-09-01",
    "kpis": {"ipca_12m_pct": 4.5, "inpc_12m_pct": 4.2},
    "history": [
        {"mes_referencia": "2026-07-01", "ipca_12m_pct": 4.1},
        {"mes_referencia": "2026-08-01", "ipca_12m_pct": 4.3},
        {"mes_referencia": "2026-09-01", "ipca_12m_pct": 4.5},
    ],
    "purchasing_power": [{"mes_referencia": "2006-01-01", "poder_compra_100_reais": 100.0}],
}


class Supabase:
    """Responde a cada consulta com a próxima lista de linhas e guarda o que foi pedido."""

    def __init__(self, *respostas: list[dict]) -> None:
        self.respostas = list(respostas)
        self.consultas: list[tuple[str, dict]] = []

    def __call__(self, sql: str, params: dict) -> list[dict]:
        self.consultas.append((sql, params))
        return self.respostas.pop(0)


@pytest.mark.parametrize(("periodo", "meses"), [(2, 2), (1, 1), (0, 3), (60, 3)])
def test_dashboard_recorta_so_o_historico_pelo_periodo(periodo: int, meses: int) -> None:
    supabase = Supabase([{"dados": DASHBOARD}])

    dados = publicacao.dashboard(supabase, localidade=3501, periodo=periodo)

    assert len(dados["history"]) == meses
    assert dados["history"][-1]["mes_referencia"] == "2026-09-01"
    assert dados["purchasing_power"] == DASHBOARD["purchasing_power"]
    assert supabase.consultas[0][1] == {"localidade": 3501}
    assert "dashboard_localidade" in supabase.consultas[0][0]


def test_dashboard_de_praca_nao_publicada_e_none() -> None:
    assert publicacao.dashboard(Supabase([]), localidade=999, periodo=12) is None


def test_buscar_produto_procura_pelo_nome_sem_diferenciar_maiusculas() -> None:
    supabase = Supabase(
        [{"codigo_subitem": "1101002", "nome": "Arroz", "nome_grupo": "Alimentação"}]
    )

    produtos = publicacao.buscar_produto(supabase, "  ARROZ ")

    assert produtos[0]["codigo_subitem"] == "1101002"
    sql, params = supabase.consultas[0]
    assert "ilike" in sql
    assert params["nome"] == "%ARROZ%"


def _previsao(localidade: int, variacao: float = 2.0) -> dict:
    return {
        "codigo_localidade": localidade,
        "nome": "Arroz",
        "mes_base": date(2026, 9, 1),
        "mes_previsto": date(2026, 10, 1),
        "variacao_prevista_pct": variacao,
        "erro_tipico_pct": 1.0,
        "variacao_mensal_pct": 0.5,
        "variacao_12m_pct": 6.0,
    }


def test_prever_reajuste_aplica_a_variacao_da_praca_da_uf_ao_preco() -> None:
    supabase = Supabase(
        [{"codigo_localidade": 3501, "nome_praca": "São Paulo"}],
        [_previsao(3501)],
    )

    resultado = publicacao.prever_reajuste(supabase, "1101002", "sp", 10.0)

    assert resultado["produto"] == "Arroz"
    assert resultado["praca"] == "São Paulo"
    assert resultado["mes_previsto"] == "2026-10-01"
    assert resultado["preco_sugerido"] == pytest.approx(10.2)
    assert resultado["faixa_preco"] == [pytest.approx(10.1), pytest.approx(10.3)]
    assert resultado["ipca_12m_pct"] == 6.0
    assert supabase.consultas[0][1] == {"uf": "SP"}
    assert supabase.consultas[1][1] == {"codigo": "1101002", "praca": 3501}


def test_prever_reajuste_usa_o_brasil_quando_a_praca_nao_tem_o_produto() -> None:
    supabase = Supabase(
        [{"codigo_localidade": 3501, "nome_praca": "São Paulo"}],
        [_previsao(1, variacao=1.0)],
    )

    resultado = publicacao.prever_reajuste(supabase, "1101002", "SP", 20.0)

    assert resultado["praca"] == "Brasil"
    assert resultado["preco_sugerido"] == pytest.approx(20.2)


@pytest.mark.parametrize(
    ("respostas", "mensagem"),
    [
        (([],), "UF"),
        (([{"codigo_localidade": 1, "nome_praca": "Brasil"}], []), "previsão"),
    ],
    ids=["uf-desconhecida", "produto-sem-previsao"],
)
def test_prever_reajuste_explica_o_que_faltou(respostas, mensagem: str) -> None:
    with pytest.raises(ValueError, match=mensagem):
        publicacao.prever_reajuste(Supabase(*respostas), "999", "XX", 10.0)


def test_prever_reajuste_recusa_preco_nao_positivo() -> None:
    with pytest.raises(ValueError, match="preço"):
        publicacao.prever_reajuste(Supabase(), "1101002", "SP", 0)


def test_destaques_ordena_pela_maior_alta_da_praca() -> None:
    linha = {
        "codigo_subitem": "1101002",
        "nome": "Arroz",
        "nome_grupo": "Alimentação",
        "variacao_prevista_pct": 3.2,
    }
    supabase = Supabase([linha])

    destaques = publicacao.destaques(supabase, localidade=3501)

    assert destaques == [linha]
    sql, params = supabase.consultas[0]
    assert params == {"localidade": 3501, "limite": 10}
    assert "order by" in sql and "desc" in sql


def test_grafico_devolve_as_linhas_ou_none() -> None:
    linhas = [{"mes_referencia": "2026-10-01", "salario_nominal": 1518}]

    assert publicacao.grafico(Supabase([{"linhas": linhas}]), "p3_salario_minimo_real") == linhas
    assert publicacao.grafico(Supabase([]), "p3_salario_minimo_real") is None


def test_buscar_produto_distingue_consumo_em_casa_e_fora_de_casa() -> None:
    """O IPCA tem o mesmo nome em 11xx (no domicílio) e 12xx (fora do domicílio)."""
    supabase = Supabase(
        [
            {"codigo_subitem": "1114083", "nome": "Refrigerante e água mineral", "nome_grupo": "A"},
            {"codigo_subitem": "1201007", "nome": "Refrigerante e água mineral", "nome_grupo": "A"},
            {"codigo_subitem": "3201001", "nome": "Refrigerador", "nome_grupo": "B"},
        ]
    )

    produtos = publicacao.buscar_produto(supabase, "refri")

    assert [p["nome"] for p in produtos] == [
        "Refrigerante e água mineral (para consumo em casa)",
        "Refrigerante e água mineral (em bar e restaurante)",
        "Refrigerador",
    ]


def test_buscar_produto_so_oferece_itens_com_previsao() -> None:
    """Item sem previsão não tem como ser simulado: nem aparece na busca."""
    supabase = Supabase([])

    publicacao.buscar_produto(supabase, "arroz")

    assert "previsao_subitem" in supabase.consultas[0][0]


def test_dashboard_de_praca_sem_poder_de_compra_usa_o_do_brasil() -> None:
    """O número-índice só existe para o Brasil: a praça mostra a série nacional, avisando."""
    praca = {**DASHBOARD, "purchasing_power": []}
    supabase = Supabase([{"dados": praca}], [{"dados": DASHBOARD}])

    dados = publicacao.dashboard(supabase, localidade=3501, periodo=0)

    assert dados["purchasing_power"] == DASHBOARD["purchasing_power"]
    assert dados["purchasing_power_brasil"] is True
    assert supabase.consultas[1][1] == {"localidade": 1}


def test_dashboard_com_poder_de_compra_proprio_nao_consulta_o_brasil() -> None:
    supabase = Supabase([{"dados": DASHBOARD}])

    dados = publicacao.dashboard(supabase, localidade=1, periodo=0)

    assert dados["purchasing_power_brasil"] is False
    assert len(supabase.consultas) == 1


def test_listar_produtos_traz_todos_com_previsao_e_nomes_distintos() -> None:
    supabase = Supabase(
        [
            {"codigo_subitem": "1101002", "nome": "Arroz", "nome_grupo": "A"},
            {"codigo_subitem": "1114084", "nome": "Cerveja", "nome_grupo": "A"},
            {"codigo_subitem": "1201048", "nome": "Cerveja", "nome_grupo": "A"},
        ]
    )

    produtos = publicacao.listar_produtos(supabase)

    assert [p["nome"] for p in produtos] == [
        "Arroz",
        "Cerveja (para consumo em casa)",
        "Cerveja (em bar e restaurante)",
    ]
    sql, params = supabase.consultas[0]
    assert "previsao_subitem" in sql and params == {}


@pytest.mark.parametrize(
    ("variacao", "erro", "confianca"),
    [(2.0, 1.0, "alta"), (8.03, 12.9, "baixa"), (0.01, 0.07, "alta"), (-3.0, 2.0, "alta"),
     (0.5, 2.01, "baixa")],
    ids=["erro-pequeno", "batata", "estavel-quase-zero", "limite-2pp", "acima-de-2pp"],
)  # fmt: skip
def test_prever_reajuste_diz_a_confianca(variacao: float, erro: float, confianca: str) -> None:
    """Confiança baixa só para item volátil: erro típico acima de 2 pontos percentuais."""
    previsao = {**_previsao(3501, variacao=variacao), "erro_tipico_pct": erro}
    supabase = Supabase([{"codigo_localidade": 3501, "nome_praca": "São Paulo"}], [previsao])

    resultado = publicacao.prever_reajuste(supabase, "1101002", "SP", 10.0)

    assert resultado["confianca"] == confianca


@pytest.mark.parametrize(
    ("variacao", "faixa"),
    [(8.03, [10.0, 12.09]), (-8.03, [7.91, 10.0])],
    ids=["alta-nao-sugere-baixar", "queda-nao-sugere-subir"],
)
def test_faixa_nao_cruza_o_preco_atual_contra_a_previsao(variacao: float, faixa) -> None:
    """Com a batata (erro 12,9 p.p.), a faixa não pode sugerir baixar o preço numa alta prevista."""
    previsao = {**_previsao(3501, variacao=variacao), "erro_tipico_pct": 12.9}
    supabase = Supabase([{"codigo_localidade": 3501, "nome_praca": "São Paulo"}], [previsao])

    resultado = publicacao.prever_reajuste(supabase, "1101002", "SP", 10.0)

    assert resultado["faixa_preco"] == [pytest.approx(faixa[0]), pytest.approx(faixa[1])]
