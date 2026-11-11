-- Clima por estação x mês (mes_referencia = YYYY-MM-01), sem buracos entre o primeiro e o
-- último mês observado de cada estação (PLAN_E3_E4.md, Seção 1.3).
--
-- A chuva do mês só sai com ao menos 80% dos dias medidos: somar menos dias subestimaria o
-- acumulado e faria um mês sem dado parecer seca. Temperatura e umidade são médias e ficam com
-- qualquer cobertura; a contagem de dias acompanha cada linha.
--
-- Anomalia = valor do mês menos a normal do mesmo mês do calendário naquela estação, calculada só
-- com os anos ANTERIORES (no mínimo 3). Usar a série inteira vazaria o futuro para o treino do
-- modelo preditivo (walk-forward, Seção 2).

with diario as (
    select * from {{ ref('stg_clima__medicao_diaria') }}
),

mensal_observado as (
    select
        estacao_id,
        cast(date_trunc('month', data_referencia) as date) as mes_referencia,
        avg(temp_media) as temp_media,
        stddev_samp(temp_media) as desvio_temp_media,
        min(temp_min) as temp_min_absoluta,
        max(temp_max) as temp_max_absoluta,
        sum(precipitacao_total_mm) as precipitacao_observada_mm,
        stddev_samp(precipitacao_total_mm) as desvio_precipitacao_mm,
        avg(umidade_relativa_media_pct) as umidade_relativa_media_pct,
        count(*) as dias_com_registro,
        count(temp_media) as dias_com_temperatura,
        count(precipitacao_total_mm) as dias_com_precipitacao,
        count(*) filter (where precipitacao_total_mm >= 1) as dias_com_chuva
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
        day(last_day(g.mes_referencia)) as dias_no_mes,
        m.temp_media,
        m.desvio_temp_media,
        m.temp_min_absoluta,
        m.temp_max_absoluta,
        case when m.chuva_completa then m.precipitacao_observada_mm end as precipitacao_total_mm,
        case when m.chuva_completa then m.dias_com_chuva end as dias_com_chuva,
        m.desvio_precipitacao_mm,
        m.umidade_relativa_media_pct,
        coalesce(m.dias_com_registro, 0) as dias_com_registro,
        coalesce(m.dias_com_temperatura, 0) as dias_com_temperatura,
        coalesce(m.dias_com_precipitacao, 0) as dias_com_precipitacao
    from grade as g
    left join (
        select
            *,
            dias_com_precipitacao >= 0.8 * day(last_day(mes_referencia)) as chuva_completa
        from mensal_observado
    ) as m using (estacao_id, mes_referencia)
),

normais as (
    -- Mesmo mês do calendário nos anos anteriores: a janela termina 1 linha antes da atual.
    select
        *,
        avg(temp_media) over anteriores as temp_media_normal,
        count(temp_media) over anteriores as anos_normal_temp,
        avg(precipitacao_total_mm) over anteriores as precipitacao_normal_mm,
        count(precipitacao_total_mm) over anteriores as anos_normal_precipitacao
    from mensal
    window anteriores as (
        partition by estacao_id, month(mes_referencia)
        order by mes_referencia
        rows between unbounded preceding and 1 preceding
    )
),

anomalias as (
    select
        *,
        case when anos_normal_temp >= 3 then temp_media - temp_media_normal end
            as temp_media_anomalia,
        case
            when anos_normal_precipitacao >= 3
                then precipitacao_total_mm - precipitacao_normal_mm
        end as precipitacao_anomalia_mm
    from normais
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
    from anomalias
    window w as (partition by estacao_id order by mes_referencia)
)

select
    d.estacao_id,
    d.mes_referencia,
    cast(d.temp_media as decimal(8, 3)) as temp_media,
    cast(d.desvio_temp_media as decimal(8, 3)) as desvio_temp_media,
    cast(d.temp_min_absoluta as decimal(8, 3)) as temp_min_absoluta,
    cast(d.temp_max_absoluta as decimal(8, 3)) as temp_max_absoluta,
    cast(d.precipitacao_total_mm as decimal(10, 3)) as precipitacao_total_mm,
    cast(d.desvio_precipitacao_mm as decimal(10, 3)) as desvio_precipitacao_mm,
    cast(d.umidade_relativa_media_pct as decimal(8, 3)) as umidade_relativa_media_pct,
    d.dias_no_mes,
    d.dias_com_registro,
    d.dias_com_temperatura,
    d.dias_com_precipitacao,
    d.dias_com_chuva,
    cast(d.temp_media_normal as decimal(8, 3)) as temp_media_normal,
    cast(d.temp_media_anomalia as decimal(8, 3)) as temp_media_anomalia,
    cast(d.precipitacao_normal_mm as decimal(10, 3)) as precipitacao_normal_mm,
    cast(d.precipitacao_anomalia_mm as decimal(10, 3)) as precipitacao_anomalia_mm,
    cast(d.temp_media_t_menos_1 as decimal(8, 3)) as temp_media_t_menos_1,
    cast(d.temp_media_t_menos_2 as decimal(8, 3)) as temp_media_t_menos_2,
    cast(d.temp_media_t_menos_3 as decimal(8, 3)) as temp_media_t_menos_3,
    cast(d.precipitacao_t_menos_1 as decimal(10, 3)) as precipitacao_t_menos_1,
    cast(d.precipitacao_t_menos_2 as decimal(10, 3)) as precipitacao_t_menos_2,
    cast(d.precipitacao_t_menos_3 as decimal(10, 3)) as precipitacao_t_menos_3,
    cast(d.temp_media_mm3 as decimal(8, 3)) as temp_media_mm3,
    mapa.codigo_localidade
from defasagens as d
left join {{ ref('seed_de_para_estacao_localidade') }} as mapa using (estacao_id)
