-- El Niño / La Niña por mês: o RONI do NOAA no formato do Banco Central (Relatório de Política
-- Monetária, set/2026, boxe "Efeito dos eventos El Niño e La Niña sobre a produtividade das
-- principais lavouras brasileiras"). Global, uma linha por mês: junta-se a qualquer fato por
-- mes_referencia.
--
-- intensidade_el_nino = RONI - 0,5 quando RONI > 0,5 (senão 0); intensidade_la_nina = |RONI| - 0,5
-- quando RONI < -0,5. fase_limiar só olha o limiar do mês: a classificação oficial de episódio
-- (5 temporadas seguidas além do limiar) depende de temporadas futuras e vazaria no treino.
--
-- VAZAMENTO: o RONI de um mês é a média móvel centrada de 3 meses, então o de setembro (ASO) usa
-- outubro e só sai no começo de novembro. mes_publicacao = mes_referencia + 2 meses. Para prever o
-- mês t, use só valores com mes_publicacao <= t (os lags de 3 a 12 meses já respeitam isso; o
-- BCB encontra efeito 9 a 16 meses antes de dezembro do ano da colheita).

with roni as (
    select * from {{ ref('stg_enso__roni') }}
),

-- A série do NOAA é contínua desde 1950 (a Bronze recusa buraco): os lags saem da série inteira e
-- só depois o fato é recortado ao período da dim_calendario (IPCA, desde 1979).
serie as (
    select
        mes_referencia,
        temporada,
        roni,
        case when roni > 0.5 then roni - 0.5 else 0 end as intensidade_el_nino,
        case when roni < -0.5 then abs(roni) - 0.5 else 0 end as intensidade_la_nina
    from roni
),

com_lags as (
select
    mes_referencia,
    cast(mes_referencia + interval 2 month as date) as mes_publicacao,
    temporada,
    roni,
    case
        when roni > 0.5 then 'el_nino'
        when roni < -0.5 then 'la_nina'
        when roni is not null then 'neutro'
    end as fase_limiar,
    cast(intensidade_el_nino as decimal(5, 2)) as intensidade_el_nino,
    cast(intensidade_la_nina as decimal(5, 2)) as intensidade_la_nina,
    {%- for k in [3, 6, 9, 12] %}
    lag(roni, {{ k }}) over w as roni_t_menos_{{ k }},
    cast(lag(intensidade_el_nino, {{ k }}) over w as decimal(5, 2))
        as intensidade_el_nino_t_menos_{{ k }},
    cast(lag(intensidade_la_nina, {{ k }}) over w as decimal(5, 2))
        as intensidade_la_nina_t_menos_{{ k }}{{ "," if not loop.last }}
    {%- endfor %}
from serie
window w as (order by mes_referencia)
)

select l.*
from com_lags as l
inner join {{ ref('dim_calendario') }} as c using (mes_referencia)
