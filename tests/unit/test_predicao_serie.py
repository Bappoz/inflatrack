import math

import pandas as pd
import pytest

from inflatrack.predicao.serie import (
    FEATURES_BASE,
    FEATURES_CLIMA,
    montar_base,
    subitens_do_atacado,
)

MESES = pd.date_range("2020-01-01", "2020-12-01", freq="MS")
CORTE = pd.Timestamp("2020-06-01")
SENTINELA = 999.0
ARROZ = "1101002"
ACUCAR = "1104003"


def _valor(mes: pd.Timestamp, base: float = 1.0) -> float:
    return SENTINELA if mes > CORTE else base


def _inflacao(codigos=(ARROZ,)) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"codigo_categoria": c, "mes_referencia": m, "variacao_mensal_pct": _valor(m)}
            for c in codigos
            for m in MESES
        ]
    )


def _enso(publicacao_atraso: int = 2) -> pd.DataFrame:
    linhas = []
    for m in MESES:
        publicado = m + pd.DateOffset(months=publicacao_atraso)
        valor = SENTINELA if publicado > CORTE else float(m.month)
        linha = {"mes_referencia": m, "mes_publicacao": publicado}
        for nome in ("intensidade_el_nino", "intensidade_la_nina"):
            linha[nome] = valor
            for lag in (3, 6, 9, 12):
                linha[f"{nome}_t_menos_{lag}"] = valor
        linhas.append(linha)
    return pd.DataFrame(linhas)


def _polos(fechado: bool = True) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "polo": "Alegrete",
                "mes_referencia": m,
                "mes_fechado": fechado,
                "temp_media_anomalia": _valor(m, 0.5),
                "spi_3": _valor(m, -1.0),
            }
            for m in MESES
        ]
    )


def _macro() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "mes_referencia": m,
                "mes_fechado": True,
                "dolar_var_mensal_pct": _valor(m, 2.0),
                "selic_acumulada_mes_pct": _valor(m, 0.8),
            }
            for m in MESES
        ]
    )


def _base(**kwargs) -> pd.DataFrame:
    partes = {"inflacao": _inflacao(), "enso": _enso(), "polos": _polos(), "macro": _macro()}
    partes.update(kwargs)
    return montar_base(**partes)


def _linha(base: pd.DataFrame, mes: str, codigo: str = ARROZ) -> pd.Series:
    return base[(base.codigo_subitem == codigo) & (base.mes == pd.Timestamp(mes))].iloc[0]


def test_alvo_e_o_mes_seguinte() -> None:
    linha = _linha(_base(), "2020-06-01")

    assert linha.y == 1.0
    assert linha.alvo == SENTINELA
    assert linha.mes_alvo == pd.Timestamp("2020-07-01")


def test_nenhuma_variavel_vem_do_futuro() -> None:
    linha = _linha(_base(), "2020-06-01")

    numericas = [c for c in FEATURES_BASE + FEATURES_CLIMA if c not in ("codigo_subitem", "grupo")]
    vazadas = [c for c in numericas if linha[c] == SENTINELA]
    assert vazadas == []


def test_enso_respeita_a_publicacao() -> None:
    """Em abr só estava publicado o ENSO de fev (publicação = referência + 2 meses)."""
    linha = _linha(_base(), "2020-04-01")

    assert linha.el_nino == 2.0


def test_clima_de_mes_nao_fechado_fica_nulo() -> None:
    linha = _linha(_base(polos=_polos(fechado=False)), "2020-06-01")

    assert math.isnan(linha.temp_anomalia_polos)
    assert math.isnan(linha.spi3_polos)


def test_subitem_fora_da_regra_5_nao_tem_clima_de_polo() -> None:
    base = _base(inflacao=_inflacao((ARROZ, ACUCAR)))

    assert _linha(base, "2020-06-01", ARROZ).temp_anomalia_polos == 0.5
    assert math.isnan(_linha(base, "2020-06-01", ACUCAR).temp_anomalia_polos)


def test_medias_e_lags_usam_so_o_passado() -> None:
    inflacao = pd.DataFrame(
        {
            "codigo_categoria": ARROZ,
            "mes_referencia": MESES,
            "variacao_mensal_pct": [float(i) for i in range(1, 13)],
        }
    )
    linha = _linha(_base(inflacao=inflacao), "2020-06-01")

    assert (linha.y, linha.y_lag1, linha.y_lag2) == (6.0, 5.0, 4.0)
    assert linha.media_3m == pytest.approx(5.0)
    assert linha.mes_do_ano_alvo == 7
    assert linha.grupo == "11"


def test_mes_faltando_nao_desalinha_os_lags() -> None:
    inflacao = _inflacao()
    inflacao = inflacao[inflacao.mes_referencia != pd.Timestamp("2020-05-01")]

    linha = _linha(_base(inflacao=inflacao), "2020-06-01")

    assert math.isnan(linha.y_lag1)


def test_subitens_caem_para_o_csv_sem_postgres() -> None:
    codigos = subitens_do_atacado("postgresql://x:y@127.0.0.1:1/z")

    assert len(codigos) == 45
    assert ARROZ in codigos
