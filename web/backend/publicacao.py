"""Leitura do que o pipeline publicou no Supabase (ver `inflatrack.reverse_etl.publicar_site`).

O site não acessa o ambiente local: o dashboard e a Felicia leem só estas tabelas, já
calculadas. Cada função recebe `consultar(sql, params) -> linhas`, para não depender de como a
conexão é aberta (e para os testes trocarem o banco por respostas prontas). Nenhum preço é
gravado: o preço que o lojista informa entra só na conta (ADR 0004).
"""

from collections.abc import Callable
from datetime import date
from typing import Any

Consultar = Callable[[str, dict[str, Any]], list[dict[str, Any]]]

BRASIL = 1


def _mes(valor: str) -> int:
    ano, mes = (int(parte) for parte in valor[:7].split("-"))
    return ano * 12 + mes


def dashboard(consultar: Consultar, localidade: int, periodo: int) -> dict[str, Any] | None:
    """O dashboard publicado da praça, com o histórico recortado aos últimos `periodo` meses.

    `periodo=0` devolve o histórico inteiro. `None` se a praça não foi publicada.
    """
    linhas = consultar(
        "select dados from dashboard_localidade where codigo_localidade = :localidade",
        {"localidade": localidade},
    )
    if not linhas:
        return None
    dados = dict(linhas[0]["dados"])
    historico = dados.get("history") or []
    if periodo and historico:
        ultimo = _mes(historico[-1]["mes_referencia"])
        dados["history"] = [h for h in historico if ultimo - _mes(h["mes_referencia"]) < periodo]
    # O número-índice do IPCA só é publicado para o Brasil: a praça usa a série nacional.
    dados["purchasing_power_brasil"] = False
    if not dados.get("purchasing_power") and localidade != BRASIL:
        brasil = dashboard(consultar, BRASIL, 0)
        if brasil:
            dados["purchasing_power"] = brasil.get("purchasing_power") or []
            dados["purchasing_power_brasil"] = True
    return dados


# No IPCA, o subgrupo 1.1 é a alimentação no domicílio e o 1.2, fora dele: o mesmo nome
# ("Cerveja", "Refrigerante e água mineral") aparece nos dois, com previsões diferentes.
_CONSUMO = {"11": "para consumo em casa", "12": "em bar e restaurante"}


_COM_PREVISAO = (
    " exists (select 1 from previsao_subitem p where p.codigo_subitem = subitem.codigo_subitem)"
)


def _nomes_distintos(produtos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Nomes repetidos ganham entre parênteses se são do consumo em casa ou fora dele."""
    nomes = [p["nome"] for p in produtos]
    return [
        {**p, "nome": f"{p['nome']} ({_CONSUMO[p['codigo_subitem'][:2]]})"}
        if nomes.count(p["nome"]) > 1 and p["codigo_subitem"][:2] in _CONSUMO
        else p
        for p in produtos
    ]


def buscar_produto(consultar: Consultar, nome: str) -> list[dict[str, Any]]:
    """Até 10 subitens do IPCA com previsão cujo nome contém `nome` (ferramenta da Felicia)."""
    return _nomes_distintos(
        consultar(
            "select codigo_subitem, nome, nome_grupo from subitem"
            f" where nome ilike :nome and{_COM_PREVISAO}"
            " order by length(nome), nome limit 10",
            {"nome": f"%{nome.strip()}%"},
        )
    )


def listar_produtos(consultar: Consultar) -> list[dict[str, Any]]:
    """Todos os subitens com previsão (cerca de 380), para o site filtrar no navegador."""
    return _nomes_distintos(
        consultar(
            "select codigo_subitem, nome, nome_grupo from subitem"
            f" where{_COM_PREVISAO} order by nome, codigo_subitem",
            {},
        )
    )


def _iso(valor: Any) -> Any:
    return valor.isoformat() if isinstance(valor, date) else valor


# Erro típico (p.p.) acima do qual o item é volátil demais para mostrar a faixa de preço.
ERRO_VOLATIL_PCT = 2.0


def _faixa(preco_atual: float, variacao: float, erro: float) -> list[float]:
    """Preço x (1 + variação ± erro), sem cruzar o preço atual contra a previsão.

    Numa alta prevista, a faixa não desce do preço atual (não sugere baixar); numa queda, não
    sobe dele.
    """
    minimo = preco_atual * (1 + (variacao - erro) / 100)
    maximo = preco_atual * (1 + (variacao + erro) / 100)
    if variacao > 0:
        minimo = max(minimo, preco_atual)
    elif variacao < 0:
        maximo = min(maximo, preco_atual)
    return [round(minimo, 2), round(maximo, 2)]


def prever_reajuste(
    consultar: Consultar, codigo_subitem: str, uf: str, preco_atual: float
) -> dict[str, Any]:
    """Preço sugerido para o mês previsto: preço x (1 + variação prevista), com a faixa de erro.

    Usa a previsão da praça do IPCA da UF; se a praça não tiver o subitem, a do Brasil.
    """
    if preco_atual <= 0:
        raise ValueError("Informe um preço atual maior que zero.")
    pracas = consultar(
        "select codigo_localidade, nome_praca from uf_praca where uf = :uf",
        {"uf": uf.strip().upper()},
    )
    if not pracas:
        raise ValueError(f"UF desconhecida: {uf}.")
    praca = pracas[0]
    previsoes = consultar(
        """
        select p.codigo_localidade, s.nome, p.mes_base, p.mes_previsto,
               p.variacao_prevista_pct, p.erro_tipico_pct,
               r.variacao_mensal_pct, r.variacao_12m_pct
        from previsao_subitem p
        join subitem s using (codigo_subitem)
        left join resumo_subitem r
            on r.codigo_localidade = p.codigo_localidade
            and r.codigo_subitem = p.codigo_subitem
        where p.codigo_subitem = :codigo and p.codigo_localidade in (:praca, 1)
        order by p.codigo_localidade = :praca desc
        limit 1
        """,
        {"codigo": codigo_subitem, "praca": praca["codigo_localidade"]},
    )
    if not previsoes:
        raise ValueError(f"Não há previsão publicada para o subitem {codigo_subitem}.")
    p = previsoes[0]
    variacao, erro = p["variacao_prevista_pct"], p["erro_tipico_pct"]
    usou_praca = p["codigo_localidade"] == praca["codigo_localidade"]
    return {
        "produto": p["nome"],
        "praca": praca["nome_praca"] if usou_praca else "Brasil",
        "mes_base": _iso(p["mes_base"]),
        "mes_previsto": _iso(p["mes_previsto"]),
        "variacao_prevista_pct": variacao,
        "erro_tipico_pct": erro,
        "preco_atual": preco_atual,
        "preco_sugerido": round(preco_atual * (1 + variacao / 100), 2),
        "faixa_preco": _faixa(preco_atual, variacao, erro),
        # Baixa: item volátil (erro típico acima de 2 p.p., o dobro do erro mediano, ~1,2 p.p.).
        # O site mostra o preço sugerido com um alerta, sem a faixa.
        "confianca": "baixa" if erro > ERRO_VOLATIL_PCT else "alta",
        "ipca_mes_pct": p["variacao_mensal_pct"],
        "ipca_12m_pct": p["variacao_12m_pct"],
    }


def destaques(consultar: Consultar, localidade: int, limite: int = 10) -> list[dict[str, Any]]:
    """Os subitens com maior alta prevista para o mês seguinte na praça."""
    return consultar(
        """
        select p.codigo_subitem, s.nome, s.nome_grupo, p.variacao_prevista_pct
        from previsao_subitem p
        join subitem s using (codigo_subitem)
        where p.codigo_localidade = :localidade
        order by p.variacao_prevista_pct desc
        limit :limite
        """,
        {"localidade": localidade, "limite": limite},
    )


def grafico(consultar: Consultar, id_grafico: str) -> list[dict[str, Any]] | None:
    """As linhas prontas de um gráfico do `painel_grafico`; `None` se não foi publicado."""
    linhas = consultar("select linhas from painel_grafico where id = :id", {"id": id_grafico})
    return linhas[0]["linhas"] if linhas else None
