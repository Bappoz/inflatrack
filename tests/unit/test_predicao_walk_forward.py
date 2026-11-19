import numpy as np
import pandas as pd
import pytest

from inflatrack.predicao import walk_forward
from inflatrack.predicao.serie import montar_base
from inflatrack.predicao.walk_forward import MODELOS, avaliar, metricas, origens_de_teste

MESES = pd.date_range("2018-01-01", "2022-12-01", freq="MS")  # 60 meses
ARROZ, CAFE = "1101002", "1114022"


def _base(inicio_cafe: str = "2018-01-01") -> pd.DataFrame:
    gerador = np.random.default_rng(1)
    linhas = [
        {"codigo_categoria": c, "mes_referencia": m, "variacao_mensal_pct": gerador.normal(0.5, 1)}
        for c in (ARROZ, CAFE)
        for m in MESES
        if not (c == CAFE and m < pd.Timestamp(inicio_cafe))
    ]
    enso = pd.DataFrame(
        {
            "mes_referencia": MESES,
            "mes_publicacao": MESES + pd.DateOffset(months=2),
            **{
                f"intensidade_{f}{s}": 0.0
                for f in ("el_nino", "la_nina")
                for s in ("", "_t_menos_3", "_t_menos_6", "_t_menos_9", "_t_menos_12")
            },
        }
    )
    polos = pd.DataFrame(
        {
            "polo": "Alegrete",
            "mes_referencia": MESES,
            "mes_fechado": True,
            "temp_media_anomalia": 0.1,
            "spi_3": 0.2,
        }
    )
    macro = pd.DataFrame(
        {
            "mes_referencia": MESES,
            "mes_fechado": True,
            "dolar_var_mensal_pct": 1.0,
            "selic_acumulada_mes_pct": 0.5,
        }
    )
    return montar_base(pd.DataFrame(linhas), enso, polos, macro)


def test_origens_sao_os_ultimos_meses_com_alvo() -> None:
    origens = origens_de_teste(_base(), meses=6)

    assert origens == list(pd.date_range("2022-06-01", "2022-11-01", freq="MS"))


def test_xgboost_so_treina_com_alvos_ja_conhecidos(monkeypatch) -> None:
    vistos: list[pd.Timestamp] = []

    def treinar(treino, colunas):
        vistos.append(treino["mes"].max())
        return None

    monkeypatch.setattr(walk_forward, "treinar_xgboost", treinar)
    monkeypatch.setattr(
        walk_forward, "prever_xgboost", lambda modelo, linhas, colunas: np.zeros(len(linhas))
    )
    base = _base()
    origens = origens_de_teste(base, meses=3)

    avaliar(base, origens)

    esperados = [o - pd.DateOffset(months=1) for o in origens for _ in range(2)]
    assert vistos == esperados


def test_avaliar_gera_todos_os_modelos_por_linha() -> None:
    base = _base()
    previsoes = avaliar(base, origens_de_teste(base, meses=2))

    assert set(previsoes["modelo"]) == set(MODELOS)
    assert len(previsoes) == 2 * 2 * len(MODELOS)  # 2 origens x 2 subitens x 8 modelos
    assert {"codigo_subitem", "grupo", "mes", "mes_alvo", "previsto", "real"} <= set(previsoes)


def test_ingenua_repete_o_mes_corrente() -> None:
    base = _base()
    origem = origens_de_teste(base, meses=1)[0]
    previsoes = avaliar(base, [origem])

    linha = base[(base.mes == origem) & (base.codigo_subitem == ARROZ)].iloc[0]
    ingenua = previsoes[(previsoes.modelo == "ingenua") & (previsoes.codigo_subitem == ARROZ)]
    assert ingenua.previsto.iloc[0] == pytest.approx(linha.y)


def test_subitem_que_comeca_tarde_nao_quebra() -> None:
    """Café com só 12 meses: sem janela de 24 para as regressões, que ficam nulas."""
    base = _base(inicio_cafe="2022-01-01")
    previsoes = avaliar(base, origens_de_teste(base, meses=2))

    regressao_cafe = previsoes[(previsoes.codigo_subitem == CAFE) & (previsoes.modelo == "linear")]
    assert regressao_cafe.previsto.isna().all()
    assert previsoes[previsoes.codigo_subitem == ARROZ].previsto.notna().all()


def _previsoes(valores: dict[str, list[float]], real: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "codigo_subitem": ARROZ,
                "grupo": "11",
                "mes_alvo": pd.Timestamp(2022, i + 1, 1),
                "modelo": modelo,
                "previsto": previsto,
                "real": real[i],
            }
            for modelo, lista in valores.items()
            for i, previsto in enumerate(lista)
        ]
    )


def test_metricas_contra_conta_a_mao() -> None:
    previsoes = _previsoes({"ingenua": [1.0, 2.0, 3.0], "linear": [1.0, 1.0, 1.0]}, [1.0, 1.0, 1.0])

    tabela = metricas(previsoes).set_index("modelo")

    assert tabela.loc["ingenua", "mae"] == pytest.approx(1.0)
    assert tabela.loc["ingenua", "rmse"] == pytest.approx(np.sqrt(5 / 3))
    assert tabela.loc["linear", "mae"] == 0.0
    assert tabela.loc["linear", "ganho_sobre_ingenua"] == pytest.approx(1.0)
    assert tabela.loc["ingenua", "ganho_sobre_ingenua"] == 0.0


def test_metricas_comparam_as_mesmas_linhas() -> None:
    previsoes = _previsoes(
        {"ingenua": [1.0, 5.0, 1.0], "linear": [1.0, np.nan, 1.0]}, [1.0, 1.0, 1.0]
    )

    tabela = metricas(previsoes).set_index("modelo")

    assert tabela.loc["ingenua", "n"] == 2
    assert tabela.loc["ingenua", "mae"] == 0.0


def test_metricas_por_grupo() -> None:
    previsoes = _previsoes({"ingenua": [2.0], "linear": [1.0]}, [1.0])

    tabela = metricas(previsoes, por=["grupo"])

    assert list(tabela.columns[:2]) == ["grupo", "modelo"]
