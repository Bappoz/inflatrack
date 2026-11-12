"""SPI-3 por estação x mês (Silver), a partir da chuva mensal já filtrada pela regra 3/5.

Modelo Python porque o SPI precisa da distribuição gama (scipy), que o SQL do DuckDB não tem. A
regra fica em ``inflatrack.common.spi`` (testada em tests/unit/test_spi.py); aqui só o ligamos ao
grafo do dbt. A gama de cada ano usa só os anos anteriores do mesmo mês (mínimo de 10): sem
vazamento para o treino walk-forward.
"""


def model(dbt, session):
    dbt.config(materialized="table")

    from inflatrack.common.spi import spi_3_meses

    mensal = dbt.ref("int_clima__anomalia_mensal").df()
    return spi_3_meses(mensal)
