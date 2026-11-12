-- Painel do clima, C7: último mês fechado de cada polo agrícola (o que o INMET já publicou
-- inteiro), com temperatura, anomalia, chuva e SPI-3. Lê serie.fct_clima_polo_mensal.
with ultimo as (
    select estacao_id, max(mes_referencia) as mes
    from serie.fct_clima_polo_mensal
    where mes_fechado
    group by estacao_id
)
select
    p.polo,
    p.uf,
    p.culturas,
    p.mes_referencia,
    p.temp_media,
    p.temp_media_anomalia,
    p.precipitacao_total_mm,
    p.precipitacao_anomalia_mm,
    p.spi_3,
    p.cobertura_dias
from serie.fct_clima_polo_mensal as p
join ultimo as u on u.estacao_id = p.estacao_id and u.mes = p.mes_referencia
order by p.polo
