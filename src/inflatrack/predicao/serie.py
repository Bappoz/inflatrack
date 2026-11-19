"""Base de treino: uma linha por subitem x mês t, com as variáveis conhecidas em t e o alvo de t+1.

Regras da Seção 2.4 do PLAN aplicadas aqui:
- Regra 1: só entra o que estava publicado em t. O ENSO entra pela data de publicação
  (`mes_publicacao <= t`), não pela de referência.
- Regra 2: clima de polo só de mês fechado, e o de t-1 (o de t pode não ter fechado na origem).
- Regra 5: o índice de clima dos polos só vai para os subitens que a tabela cobre.
- Regra 7: nada é imputado; nulo fica nulo (o XGBoost lida com ele).
Médias, desvio e defasagens são calculados aqui só com meses <= t, não lidos da Gold.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import psycopg

from inflatrack.common.db import dsn_do_ambiente

RAIZ = Path(__file__).resolve().parents[3]
TABELA_EXEMPLO = RAIZ / "data" / "atacado" / "tabela_exemplo.csv"

_HORTALICAS = ("Itapeva", "Irecê", "Ituporanga")
_GRAOS_CARNES = ("Sorriso", "Rio Verde", "Dourados", "Passo Fundo", "Barreiras")
_CAFE = ("Varginha", "Patrocínio", "Linhares")

# Subitem -> polos agrícolas (Seção 2.4, Regra 5). Fora daqui, o clima de polo fica nulo.
GRUPO_CLIMA: dict[str, tuple[str, ...]] = {
    "1103003": _HORTALICAS,  # batata-inglesa
    "1103043": _HORTALICAS,  # cebola
    "1103028": _HORTALICAS,  # tomate
    "1103044": _HORTALICAS,  # cenoura
    "1101002": ("Alegrete",),  # arroz
    "1101073": ("Unaí", "Irecê"),  # feijão carioca
    "1101052": ("Unaí", "Irecê"),  # feijão preto
    "1114022": _CAFE,  # café moído
    "1111004": ("Juiz de Fora",),  # leite longa vida
    "1111009": ("Juiz de Fora",),  # leite em pó
    "1111011": ("Juiz de Fora",),  # queijo
    "1111031": ("Juiz de Fora",),  # manteiga
    "1113013": _GRAOS_CARNES,  # óleo de soja
    "1107095": _GRAOS_CARNES,  # acém
    "1107018": _GRAOS_CARNES,  # carne de porco
    "1110009": _GRAOS_CARNES,  # frango inteiro
}

# Uma série é um subitem numa praça: defasagens e médias nunca atravessam praças.
CHAVE_SERIE = ["codigo_localidade", "codigo_subitem"]

FEATURES_BASE = [
    "codigo_localidade",
    "y",
    "y_lag1",
    "y_lag2",
    "media_3m",
    "media_6m",
    "media_12m",
    "desvio_12m",
    "mes_do_ano_alvo",
    "codigo_subitem",
    "grupo",
    "dolar_var_mensal_pct",
    "selic_acumulada_mes_pct",
]

_LAGS_ENSO = (3, 6, 9, 12)
FEATURES_CLIMA = [
    "el_nino",
    "la_nina",
    *[f"{fase}_t{lag}" for lag in _LAGS_ENSO for fase in ("el_nino", "la_nina")],
    "temp_anomalia_polos",
    "spi3_polos",
]


def montar_base(
    inflacao: pd.DataFrame, enso: pd.DataFrame, polos: pd.DataFrame, macro: pd.DataFrame
) -> pd.DataFrame:
    """`inflacao`: codigo_localidade (opcional; sem ela, Brasil), codigo_categoria,
    mes_referencia e variacao_mensal_pct."""
    if "codigo_localidade" not in inflacao:
        inflacao = inflacao.assign(codigo_localidade=1)
    base = _serie_completa(inflacao)
    por_subitem = base.groupby(CHAVE_SERIE, observed=True)["y"]
    base["y_lag1"] = por_subitem.shift(1)
    base["y_lag2"] = por_subitem.shift(2)
    for janela in (3, 6, 12):
        base[f"media_{janela}m"] = por_subitem.transform(
            lambda s, j=janela: s.rolling(j, min_periods=j).mean()
        )
    base["desvio_12m"] = por_subitem.transform(lambda s: s.rolling(12, min_periods=12).std())
    base["alvo"] = por_subitem.shift(-1)
    base["mes_alvo"] = base["mes"] + pd.DateOffset(months=1)
    base["mes_do_ano_alvo"] = base["mes_alvo"].dt.month
    base["grupo"] = base["codigo_subitem"].str[:2]

    base = _juntar_macro(base, macro)
    base = _juntar_enso(base, enso)
    base = _juntar_polos(base, polos)
    for coluna in ("codigo_localidade", "codigo_subitem", "grupo"):
        base[coluna] = base[coluna].astype("category")
    return base.sort_values([*CHAVE_SERIE, "mes"]).reset_index(drop=True)


def _serie_completa(inflacao: pd.DataFrame) -> pd.DataFrame:
    """Reindexa cada série (praça x subitem) para todos os meses entre o primeiro e o último: um
    mês que falta vira nulo em vez de encostar o vizinho e desalinhar as defasagens."""
    partes = []
    for (praca, codigo), grupo in inflacao.groupby(["codigo_localidade", "codigo_categoria"]):
        serie = (
            grupo.assign(mes=pd.to_datetime(grupo["mes_referencia"]))
            .set_index("mes")["variacao_mensal_pct"]
            .astype(float)
        )
        meses = pd.date_range(serie.index.min(), serie.index.max(), freq="MS")
        partes.append(
            pd.DataFrame(
                {
                    "codigo_localidade": int(praca),
                    "codigo_subitem": codigo,
                    "mes": meses,
                    "y": serie.reindex(meses).values,
                }
            )
        )
    return pd.concat(partes, ignore_index=True)


def _juntar_macro(base: pd.DataFrame, macro: pd.DataFrame) -> pd.DataFrame:
    fechado = macro[macro["mes_fechado"]].assign(mes=lambda d: pd.to_datetime(d["mes_referencia"]))
    colunas = ["dolar_var_mensal_pct", "selic_acumulada_mes_pct"]
    return base.merge(
        fechado[["mes", *colunas]].astype({c: float for c in colunas}), on="mes", how="left"
    )


def _juntar_enso(base: pd.DataFrame, enso: pd.DataFrame) -> pd.DataFrame:
    renomear = {"intensidade_el_nino": "el_nino", "intensidade_la_nina": "la_nina"}
    for lag in _LAGS_ENSO:
        renomear[f"intensidade_el_nino_t_menos_{lag}"] = f"el_nino_t{lag}"
        renomear[f"intensidade_la_nina_t_menos_{lag}"] = f"la_nina_t{lag}"
    publicado = (
        enso.assign(mes_publicacao=lambda d: pd.to_datetime(d["mes_publicacao"]))
        .rename(columns=renomear)[["mes_publicacao", *renomear.values()]]
        .sort_values("mes_publicacao")
        .astype({c: float for c in renomear.values()})
    )
    ordenada = base.sort_values("mes")
    juntos = pd.merge_asof(
        ordenada, publicado, left_on="mes", right_on="mes_publicacao", direction="backward"
    )
    return juntos.drop(columns="mes_publicacao")


def _juntar_polos(base: pd.DataFrame, polos: pd.DataFrame) -> pd.DataFrame:
    mapa = pd.DataFrame(
        [(codigo, polo) for codigo, lista in GRUPO_CLIMA.items() for polo in lista],
        columns=["codigo_subitem", "polo"],
    )
    # O clima de t entra na linha de t+1: na origem t (IPCA de t sai ~dia 10 de t+1) o pacote do
    # BDMEP de t muitas vezes ainda não fechou. O `mes_fechado` é o de hoje, não o daquela data,
    # então usar t daria ao backtest um clima que a previsão real não teria.
    fechado = polos[polos["mes_fechado"].astype(bool)].assign(
        mes=lambda d: pd.to_datetime(d["mes_referencia"]) + pd.DateOffset(months=1)
    )
    por_subitem = (
        mapa.merge(fechado, on="polo")
        .groupby(["codigo_subitem", "mes"], as_index=False)
        .agg(temp_anomalia_polos=("temp_media_anomalia", "mean"), spi3_polos=("spi_3", "mean"))
    )
    return base.merge(por_subitem, on=["codigo_subitem", "mes"], how="left")


def carregar_gold(
    caminho_duckdb: Path, codigos: list[str] | None, codigo_localidade: int | None
) -> pd.DataFrame:
    """Lê as fatos da Gold (só leitura) e monta a base. `None` em `codigos` ou em
    `codigo_localidade` quer dizer todos os subitens ou todas as praças."""
    with duckdb.connect(str(caminho_duckdb), read_only=True) as conexao:
        inflacao = conexao.execute(
            "select codigo_localidade, codigo_categoria, mes_referencia, variacao_mensal_pct"
            " from gold.fct_inflacao_mensal"
            " where indice = 'IPCA' and nivel_categoria = 'subitem'"
            " and (?::integer is null or codigo_localidade = ?)"
            " and (?::varchar[] is null or codigo_categoria in (select unnest(?::varchar[])))",
            [codigo_localidade, codigo_localidade, codigos, codigos],
        ).df()
        enso = conexao.execute("select * from gold.fct_enso_mensal").df()
        polos = conexao.execute(
            "select polo, mes_referencia, mes_fechado, temp_media_anomalia, spi_3"
            " from gold.fct_clima_polo_mensal"
        ).df()
        macro = conexao.execute(
            "select mes_referencia, mes_fechado, dolar_var_mensal_pct, selic_acumulada_mes_pct"
            " from gold.fct_macroeconomia_mensal"
        ).df()
    return montar_base(inflacao, enso, polos, macro)


def subitens_do_atacado(dsn: str | None = None) -> list[str]:
    """Os subitens dos produtos do atacadista (só os códigos, nunca o preço).

    Sem Postgres, usa a tabela de exemplo versionada.
    """
    try:
        with psycopg.connect(dsn or dsn_do_ambiente(), connect_timeout=3) as conexao:
            codigos = [
                codigo
                for (codigo,) in conexao.execute(
                    "select distinct codigo_subitem_ipca from atacado.produto order by 1"
                )
            ]
        if codigos:
            return codigos
    except psycopg.Error:
        pass
    from inflatrack.atacado.importar_tabela import ler_csv

    linhas = ler_csv(TABELA_EXEMPLO.read_text(encoding="utf-8"))
    return sorted({linha.codigo_subitem_ipca for linha in linhas})
