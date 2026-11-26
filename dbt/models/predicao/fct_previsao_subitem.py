"""Previsão da variação do subitem do IPCA no mês seguinte ao último divulgado (Gold).

Uma linha por praça e subitem, com o erro típico do modelo naquele subitem. É o XGBoost fixo,
escolhido no ponto de parada (docs/evidencias/e4/avaliacao_todas_pracas.md). A regra fica em
``inflatrack.predicao.aplicacao`` (testada em tests/unit/test_predicao_aplicacao.py); aqui só a
ligamos ao grafo do dbt.

Pesa (13 treinos do XGBoost, alguns minutos): fica no grupo ``predicao`` do Dagster e roda no
``predicao_job`` mensal, não no ``analitico_job`` diário. Nenhum preço entra aqui (ADR 0004).
"""


def model(dbt, session):
    dbt.config(materialized="table")

    import pandas as pd

    from inflatrack.predicao.aplicacao import tabela_previsao
    from inflatrack.predicao.serie import montar_base

    inflacao = (
        dbt.ref("fct_inflacao_mensal")
        .filter("indice = 'IPCA' and nivel_categoria = 'subitem'")
        .project("codigo_localidade, codigo_categoria, mes_referencia, variacao_mensal_pct")
        .df()
    )
    enso = dbt.ref("fct_enso_mensal").df()
    polos = (
        dbt.ref("fct_clima_polo_mensal")
        .project("polo, mes_referencia, mes_fechado, temp_media_anomalia, spi_3")
        .df()
    )
    macro = (
        dbt.ref("fct_macroeconomia_mensal")
        .project("mes_referencia, mes_fechado, dolar_var_mensal_pct, selic_acumulada_mes_pct")
        .df()
    )
    base = montar_base(inflacao, enso, polos, macro)
    return tabela_previsao(base, gerado_em=pd.Timestamp.now(tz="UTC"))
