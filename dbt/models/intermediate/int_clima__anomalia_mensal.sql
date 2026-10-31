with diario as (
    select * from {{ ref('stg_clima__medicao_diaria') }}
),
mensal_observado as (
    select
        estacao_id,
        cast(date_trunc('month', data_referencia) as date) as mes_referencia,
        avg(temp_media) as temp_media,
        stddev_samp(temp_media) as desvio_temp_media,
        sum(precipitacao_total_mm) as precipitacao_total_mm,
        stddev_samp(precipitacao_total_mm) as desvio_precipitacao_mm,
        avg(umidade_relativa_media_pct) as umidade_relativa_media_pct,
        count(*) as dias_com_registro,
        count(temp_media) as dias_com_temperatura
    from diario
    group by estacao_id, mes_referencia
),
limites as (
    select estacao_id, min(mes_referencia) as primeiro_mes, max(mes_referencia) as ultimo_mes
    from mensal_observado
    group by estacao_id
),
grade as (
    select l.estacao_id, cast(g.mes as date) as mes_referencia
    from limites as l,
        generate_series(l.primeiro_mes, l.ultimo_mes, interval 1 month) as g(mes)
),
mensal as (
    select
        g.estacao_id,
        g.mes_referencia,
        m.temp_media,
        m.desvio_temp_media,
        m.precipitacao_total_mm,
        m.desvio_precipitacao_mm,
        m.umidade_relativa_media_pct,
        coalesce(m.dias_com_registro, 0) as dias_com_registro,
        coalesce(m.dias_com_temperatura, 0) as dias_com_temperatura
    from grade as g
    left join mensal_observado as m using (estacao_id, mes_referencia)
),
defasagens as (
    select
        *,
        lag(temp_media, 1) over w as temp_media_t_menos_1,
        lag(temp_media, 2) over w as temp_media_t_menos_2,
        lag(temp_media, 3) over w as temp_media_t_menos_3,
        lag(precipitacao_total_mm, 1) over w as precipitacao_t_menos_1,
        lag(precipitacao_total_mm, 2) over w as precipitacao_t_menos_2,
        lag(precipitacao_total_mm, 3) over w as precipitacao_t_menos_3,
        avg(temp_media) over (w rows between 2 preceding and current row) as temp_media_mm3
    from mensal
    window w as (partition by estacao_id order by mes_referencia)
)
select
    estacao_id,
    mes_referencia,
    cast(temp_media as decimal(8, 3)) as temp_media,
    cast(desvio_temp_media as decimal(8, 3)) as desvio_temp_media,
    cast(precipitacao_total_mm as decimal(10, 3)) as precipitacao_total_mm,
    cast(desvio_precipitacao_mm as decimal(10, 3)) as desvio_precipitacao_mm,
    cast(umidade_relativa_media_pct as decimal(8, 3)) as umidade_relativa_media_pct,
    dias_com_registro,
    dias_com_temperatura,
    cast(mapa.codigo_ibge as varchar) as codigo_localidade
from defasagens
left join {{ ref('seed_de_para_estacao_localidade') }} as mapa using (estacao_id)
    cast(temp_media_t_menos_2 as decimal(8, 3)) as temp_media_t_menos_2,
    cast(temp_media_t_menos_3 as decimal(8, 3)) as temp_media_t_menos_3,
    cast(precipitacao_t_menos_1 as decimal(10, 3)) as precipitacao_t_menos_1,
    cast(precipitacao_t_menos_2 as decimal(10, 3)) as precipitacao_t_menos_2,
    cast(precipitacao_t_menos_3 as decimal(10, 3)) as precipitacao_t_menos_3,
    cast(temp_media_mm3 as decimal(8, 3)) as temp_media_mm3
from defasagens