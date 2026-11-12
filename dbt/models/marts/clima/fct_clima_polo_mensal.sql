-- Clima dos polos agrícolas x mês: onde os alimentos da cesta são plantados (grãos, arroz, café,
-- feijão e hortaliças, leite), e não onde são consumidos. Complementa fct_clima_mensal (praças do
-- IPCA): o Banco Central e a Conab medem o efeito do clima nas regiões produtoras.
--
-- Uma estação por polo (seed_estacao_polo_agricola). A grade de meses vem de
-- int_clima__anomalia_mensal (completa por estação), então os lags são sempre meses de
-- calendário. Mesmas regras de fct_clima_mensal: regra 3/5 da OMM, normais e SPI-3 só com anos
-- anteriores (sem vazamento), mes_fechado só pelo dado oficial e dias_provisorios do Open-Meteo.

with polo as (
    select * from {{ ref('seed_estacao_polo_agricola') }}
),

serie as (
    select a.*, spi.precipitacao_3m_mm, spi.spi_3
    from {{ ref('int_clima__anomalia_mensal') }} as a
    inner join polo using (estacao_id)
    left join {{ ref('int_clima__spi_mensal') }} as spi using (estacao_id, mes_referencia)
),

-- Último dia publicado pelo INMET em cada estação (só o oficial).
ultima_leitura as (
    select d.estacao_id, max(d.data_referencia) filter (where d.observado) as data_referencia
    from {{ ref('stg_clima__medicao_diaria') }} as d
    inner join polo using (estacao_id)
    group by d.estacao_id
)

select
    s.estacao_id,
    p.polo,
    p.uf,
    p.culturas,
    s.mes_referencia,
    coalesce(last_day(s.mes_referencia) <= u.data_referencia, false) as mes_fechado,
    s.dias_com_registro,
    s.dias_provisorios,
    s.dias_no_mes,
    {{ colunas_clima_mensal('s') }}
from serie as s
inner join polo as p using (estacao_id)
left join ultima_leitura as u using (estacao_id)
window w as (partition by s.estacao_id order by s.mes_referencia)
