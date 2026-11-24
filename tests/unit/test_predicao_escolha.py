import numpy as np
import pandas as pd
import pytest

from inflatrack.predicao.escolha import aplicar_escolha, avaliar_escolha, escolher_por_subitem

MESES = pd.date_range("2024-01-01", periods=6, freq="MS")
ARROZ, CAFE = "1101002", "1114022"


def _previsoes(erros: dict[tuple[str, str], float], real: float = 1.0) -> pd.DataFrame:
    """Uma linha por (praça, subitem, mês, modelo), com erro fixo por (subitem, modelo)."""
    return pd.DataFrame(
        [
            {
                "codigo_localidade": praca,
                "codigo_subitem": codigo,
                "grupo": codigo[:2],
                "mes_alvo": mes,
                "modelo": modelo,
                "previsto": real + erro,
                "real": real,
            }
            for (codigo, modelo), erro in erros.items()
            for praca in (1, 3501)
            for mes in MESES
        ]
    )


ERROS = {
    (ARROZ, "ingenua"): 0.0,
    (ARROZ, "xgboost_sem_clima"): 0.5,
    (CAFE, "ingenua"): 0.8,
    (CAFE, "xgboost_sem_clima"): 0.2,
}


def test_vence_o_modelo_de_menor_erro_por_subitem() -> None:
    escolha = escolher_por_subitem(_previsoes(ERROS)).set_index("codigo_subitem")

    assert escolha.loc[ARROZ, "modelo"] == "ingenua"
    assert escolha.loc[CAFE, "modelo"] == "xgboost_sem_clima"
    assert escolha.loc[CAFE, "erro_tipico_pct"] == pytest.approx(0.2)


def test_reserva_e_a_ingenua_quando_o_vencedor_nao_previu() -> None:
    previsoes = _previsoes(ERROS)
    falha = (
        (previsoes.codigo_subitem == CAFE)
        & (previsoes.modelo == "xgboost_sem_clima")
        & (previsoes.codigo_localidade == 3501)
    )
    previsoes.loc[falha, "previsto"] = np.nan
    escolha = pd.DataFrame(
        {
            "codigo_subitem": [ARROZ, CAFE],
            "modelo": ["ingenua", "xgboost_sem_clima"],
            "erro_tipico_pct": [0.0, 0.2],
        }
    )

    aplicada = aplicar_escolha(previsoes, escolha)

    cafe_sp = aplicada[(aplicada.codigo_subitem == CAFE) & (aplicada.codigo_localidade == 3501)]
    assert set(cafe_sp.modelo_usado) == {"ingenua"}
    assert cafe_sp.previsto.notna().all()
    assert set(aplicada.modelo) == {"escolha_por_subitem"}


def test_escolha_nao_ve_os_meses_em_que_e_medida() -> None:
    previsoes = _previsoes(ERROS)
    medidos = previsoes.mes_alvo >= MESES[4]
    mexida = previsoes.copy()
    # Nos meses de medição o XGBoost do arroz passa a acertar tudo; a escolha não pode mudar.
    mexida.loc[
        medidos & (mexida.codigo_subitem == ARROZ) & (mexida.modelo != "ingenua"), "previsto"
    ] = 1.0

    original = avaliar_escolha(previsoes, meses_escolha=4)
    com_futuro = avaliar_escolha(mexida, meses_escolha=4)

    usado = lambda d: set(  # noqa: E731
        d[(d.modelo == "escolha_por_subitem") & (d.codigo_subitem == ARROZ)].modelo_usado
    )
    assert usado(original) == usado(com_futuro) == {"ingenua"}
    assert com_futuro.mes_alvo.min() == MESES[4]


def test_avaliar_escolha_traz_os_candidatos_nos_mesmos_meses() -> None:
    resultado = avaliar_escolha(_previsoes(ERROS), meses_escolha=4)

    assert set(resultado.modelo) == {"ingenua", "xgboost_sem_clima", "escolha_por_subitem"}
    assert resultado.groupby("modelo").mes_alvo.min().eq(MESES[4]).all()
