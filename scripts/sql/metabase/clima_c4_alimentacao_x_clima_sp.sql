-- Painel do clima, C4: inflação de alimentos x clima em São Paulo, desde ago/2016 (início do SPI-3).
-- Variação mensal do grupo Alimentação e bebidas do IPCA, anomalia de temperatura do mês (°C)
-- e SPI-3 (seca abaixo de -1). Lê serie.fct_inflacao_mensal e serie.fct_clima_mensal.
select
    f.mes_referencia,
    f.variacao_mensal_pct as ipca_alimentacao_pct,
    c.temp_media_anomalia as anomalia_temperatura_c,
    c.spi_3
from serie.fct_inflacao_mensal as f
join serie.fct_clima_mensal as c
    on c.codigo_localidade = f.codigo_localidade and c.mes_referencia = f.mes_referencia
where f.indice = 'IPCA'
    and f.codigo_categoria = '1'
    and f.codigo_localidade = 3501
    and f.mes_referencia >= date '2016-08-01'
order by f.mes_referencia
