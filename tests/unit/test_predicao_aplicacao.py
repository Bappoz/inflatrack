import numpy as np
import pandas as pd
import pytest

from inflatrack.predicao import aplicacao
from inflatrack.predicao.aplicacao import erro_tipico, prever_proximo_mes, tabela_previsao
from inflatrack.predicao.serie import montar_base

MESES = pd.date_range("2019-01-01", "2022-12-01", freq="MS")  # 48 meses
ARROZ, FEIJAO, CAFE = "1101002", "1101073", "1114022"


def _base(series: dict[tuple[int, str], pd.DatetimeIndex] | None = None) -> pd.DataFrame:
    series = series or {(1, ARROZ): MESES, (3501, ARROZ): MESES, (1, CAFE): MESES}
    gerador = np.random.default_rng(3)
    linhas = [
        {
            "codigo_localidade": praca,
            "codigo_categoria": codigo,
            "mes_referencia": mes,
            "variacao_mensal_pct": gerador.normal(0.5, 1),
        }
        for (praca, codigo), meses in series.items()
        for mes in meses
    ]
    vazio = {"mes_referencia": MESES}
    enso = pd.DataFrame(
        {
            **vazio,
            "mes_publicacao": MESES + pd.DateOffset(months=2),
            **{
                f"intensidade_{f}{s}": 0.0
                for f in ("el_nino", "la_nina")
                for s in ("", "_t_menos_3", "_t_menos_6", "_t_menos_9", "_t_menos_12")
            },
        }
    )
    polos = pd.DataFrame(
        {**vazio, "polo": "Alegrete", "mes_fechado": True, "temp_media_anomalia": 0.0, "spi_3": 0.0}
    )
    macro = pd.DataFrame(
        {**vazio, "mes_fechado": True, "dolar_var_mensal_pct": 0.0, "selic_acumulada_mes_pct": 0.0}
    )
    return montar_base(pd.DataFrame(linhas), enso, polos, macro)


def test_preve_o_mes_seguinte_ao_ultimo_ipca() -> None:
    previsao = prever_proximo_mes(_base())

    assert set(previsao.mes_base) == {pd.Timestamp("2022-12-01")}
    assert set(previsao.mes_previsto) == {pd.Timestamp("2023-01-01")}
    assert len(previsao) == 3
    assert previsao.variacao_prevista_pct.notna().all()


def test_treino_so_ve_alvos_ja_conhecidos(monkeypatch) -> None:
    vistos = []
    original = aplicacao.treinar_xgboost

    def espiao(treino, colunas):
        vistos.append(treino["mes"].max())
        return original(treino, colunas)

    monkeypatch.setattr(aplicacao, "treinar_xgboost", espiao)

    prever_proximo_mes(_base())

    assert vistos == [pd.Timestamp("2022-11-01")]


def test_serie_sem_ipca_no_ultimo_mes_fica_sem_previsao() -> None:
    curta = MESES[: MESES.get_loc(pd.Timestamp("2022-06-01")) + 1]
    base = _base({(1, ARROZ): MESES, (3501, ARROZ): curta})

    previsao = prever_proximo_mes(base)

    assert list(previsao.codigo_localidade) == [1]


def test_subitem_sem_previsao_na_janela_recebe_o_erro_do_grupo() -> None:
    """Feijão só começa 4 meses antes do fim: sem alvo na janela de 12, herda o MAE do grupo 1."""
    base = _base(
        {
            (1, ARROZ): MESES,
            (1, CAFE): MESES,
            (1, FEIJAO): MESES[-1:],
        }
    )

    erros = erro_tipico(base, meses=12).set_index("codigo_subitem").erro_tipico_pct

    assert erros[FEIJAO] == pytest.approx(erros[[ARROZ, CAFE]].mean(), rel=0.2)
    assert (erros >= 0).all()


def test_tabela_previsao_tem_chave_unica_e_todos_os_campos() -> None:
    gerado = pd.Timestamp("2026-11-19 12:00", tz="UTC")

    tabela = tabela_previsao(_base(), gerado_em=gerado)

    assert not tabela.duplicated(["codigo_localidade", "codigo_subitem"]).any()
    assert list(tabela.columns) == [
        "codigo_localidade",
        "codigo_subitem",
        "mes_base",
        "mes_previsto",
        "variacao_prevista_pct",
        "erro_tipico_pct",
        "gerado_em",
    ]
    assert tabela.erro_tipico_pct.notna().all()
