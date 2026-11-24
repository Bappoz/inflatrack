-- Uma linha por estação x dia. O dado oficial é o do INMET (BDMEP, última revisão). Depois do
-- último dia que o INMET publicou, até ontem, entra o provisório do Open-Meteo (modelo em grade,
-- observado = false). Quando o pacote seguinte do INMET chega, o corte avança e o provisório
-- daqueles dias sai daqui sozinho; ele nunca preenche buraco do histórico oficial.

with oficial as (
    select
        id_medicao,
        estacao_id,
        cast(data_referencia as date) as data_referencia,
        cast(temp_min as decimal(8, 3)) as temp_min,
        cast(temp_max as decimal(8, 3)) as temp_max,
        cast(temp_media as decimal(8, 3)) as temp_media,
        cast(precipitacao_total_mm as decimal(10, 3)) as precipitacao_total_mm,
        cast(umidade_relativa_media_pct as decimal(8, 3)) as umidade_relativa_media_pct,
        cast(umidade_relativa_min_pct as decimal(8, 3)) as umidade_relativa_min_pct,
        horas_com_registro,
        observado,
        'inmet_bdmep' as fonte,
        _ingerido_em
    from {{ source('bronze_clima', 'clima_medicao') }}
    qualify row_number() over (
        partition by estacao_id, data_referencia
        order by _ingerido_em desc, id_medicao desc
    ) = 1
),

corte as (
    select max(data_referencia) as ultimo_dia_oficial from oficial
),

provisoria as (
    select
        p.id_medicao,
        p.estacao_id,
        cast(p.data_referencia as date) as data_referencia,
        cast(p.temp_min as decimal(8, 3)) as temp_min,
        cast(p.temp_max as decimal(8, 3)) as temp_max,
        cast(p.temp_media as decimal(8, 3)) as temp_media,
        cast(p.precipitacao_total_mm as decimal(10, 3)) as precipitacao_total_mm,
        cast(p.umidade_relativa_media_pct as decimal(8, 3)) as umidade_relativa_media_pct,
        cast(p.umidade_relativa_min_pct as decimal(8, 3)) as umidade_relativa_min_pct,
        cast(null as smallint) as horas_com_registro,
        false as observado,
        p.fonte,
        p._ingerido_em
    from {{ source('bronze_clima', 'clima_medicao_provisoria') }} as p
    cross join corte as c
    where cast(p.data_referencia as date) > c.ultimo_dia_oficial
    qualify row_number() over (
        partition by p.estacao_id, p.data_referencia
        order by p._ingerido_em desc, p.id_medicao desc
    ) = 1
)

select * from oficial
union all
select * from provisoria
