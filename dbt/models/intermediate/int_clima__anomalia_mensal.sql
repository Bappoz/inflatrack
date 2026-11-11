-- Clima por estação x mês (mes_referencia = YYYY-MM-01), sem buracos entre o primeiro e o
-- último mês observado de cada estação (PLAN_E3_E4.md, Seção 1.3).
--
-- Regra 3/5 da OMM (WMO-No. 1203): o valor do mês só sai se faltarem no máximo 5 dias no total
-- e no máximo 3 dias seguidos. Vale separadamente para cada variável:
--   * temperatura (média, mínima, máxima e desvio) e umidade: médias; conta como falta só o dia
--     que JÁ PASSOU sem leitura, então o mês em curso tem média dos dias decorridos;
--   * chuva (e dias com chuva): total; conta como falta todo dia sem leitura, inclusive os que
--     ainda não aconteceram, porque somar parte do mês faria o mês parecer seco.
-- O padrão estrito da OMM para totais é 0 dia faltando; a 3/5 também na chuva foi decisão do
-- projeto (2026-11-11), para não perder ~18% dos meses de séries já curtas.
--
-- Dias provisórios (Open-Meteo, só depois do último dia publicado pelo INMET) entram nas médias do
-- mês em curso e são contados em dias_provisorios. As normais dos anos anteriores são sempre
-- oficiais: o provisório de um dia sai da staging quando o INMET o publica.
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
        count(*) filter (where precipitacao_total_mm >= 1) as dias_com_chuva,
        count(*) filter (where not observado) as dias_provisorios
    from diario
    group by estacao_id, mes_referencia
),

limites as (
    select estacao_id, min(mes_referencia) as primeiro_mes, max(mes_referencia) as ultimo_mes
    from mensal_observado
    group by estacao_id
),

-- Último dia com dado na série (oficial ou provisório): depois dele, o dia ainda não aconteceu.
ultimo_dia as (
    select max(data_referencia) as dia from diario
),

presenca as (
    select
        l.estacao_id,
        cast(g.dia as date) as dia,
        cast(date_trunc('month', g.dia) as date) as mes_referencia,
        cast(g.dia as date) <= u.dia as decorrido,
        d.temp_media is not null as tem_temperatura,
        d.umidade_relativa_media_pct is not null as tem_umidade,
        d.precipitacao_total_mm is not null as tem_chuva
    from limites as l
    cross join ultimo_dia as u
    cross join generate_series(l.primeiro_mes, last_day(l.ultimo_mes), interval 1 day) as g(dia)
    left join diario as d
        on d.estacao_id = l.estacao_id and d.data_referencia = cast(g.dia as date)
),

faltas as (
    select estacao_id, mes_referencia, 'temperatura' as variavel, dia
    from presenca where decorrido and not tem_temperatura
    union all
    select estacao_id, mes_referencia, 'umidade', dia
    from presenca where decorrido and not tem_umidade
    union all
    select estacao_id, mes_referencia, 'chuva', dia
    from presenca where not tem_chuva
),

-- Dias seguidos sem leitura: dia - posição na fila é constante dentro de cada sequência.
sequencias as (
    select estacao_id, mes_referencia, variavel, count(*) as tamanho
    from (
        select
            *,
            dia - cast(row_number() over (
                partition by estacao_id, mes_referencia, variavel order by dia
            ) as integer) as grupo
        from faltas
    )
    group by estacao_id, mes_referencia, variavel, grupo
),

regra_3_5 as (
    select
        estacao_id,
        mes_referencia,
        coalesce(sum(tamanho) filter (where variavel = 'temperatura'), 0)
            as dias_sem_temperatura,
        coalesce(max(tamanho) filter (where variavel = 'temperatura'), 0)
            as maior_sequencia_sem_temperatura,
        coalesce(sum(tamanho) filter (where variavel = 'umidade'), 0) as dias_sem_umidade,
        coalesce(max(tamanho) filter (where variavel = 'umidade'), 0)
            as maior_sequencia_sem_umidade,
        coalesce(sum(tamanho) filter (where variavel = 'chuva'), 0) as dias_sem_chuva_medida,
        coalesce(max(tamanho) filter (where variavel = 'chuva'), 0)
            as maior_sequencia_sem_chuva
    from sequencias
    group by estacao_id, mes_referencia
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
        case when coalesce(r.temperatura_valida, true) then m.temp_media end as temp_media,
        case when coalesce(r.temperatura_valida, true) then m.desvio_temp_media end as desvio_temp_media,
        case when coalesce(r.temperatura_valida, true) then m.temp_min_absoluta end as temp_min_absoluta,
        case when coalesce(r.temperatura_valida, true) then m.temp_max_absoluta end as temp_max_absoluta,
        case when coalesce(r.chuva_valida, true) then m.precipitacao_observada_mm end as precipitacao_total_mm,
        case when coalesce(r.chuva_valida, true) then m.dias_com_chuva end as dias_com_chuva,
        case when coalesce(r.chuva_valida, true) then m.desvio_precipitacao_mm end as desvio_precipitacao_mm,
        case when coalesce(r.umidade_valida, true) then m.umidade_relativa_media_pct end
            as umidade_relativa_media_pct,
        coalesce(m.dias_com_registro, 0) as dias_com_registro,
        coalesce(m.dias_com_temperatura, 0) as dias_com_temperatura,
        coalesce(m.dias_com_precipitacao, 0) as dias_com_precipitacao,
        coalesce(m.dias_provisorios, 0) as dias_provisorios,
        coalesce(r.dias_sem_temperatura, 0) as dias_sem_temperatura,
        coalesce(r.maior_sequencia_sem_temperatura, 0) as maior_sequencia_sem_temperatura,
        coalesce(r.dias_sem_chuva_medida, 0) as dias_sem_chuva_medida,
        coalesce(r.maior_sequencia_sem_chuva, 0) as maior_sequencia_sem_chuva
    from grade as g
    left join mensal_observado as m using (estacao_id, mes_referencia)
    -- Mês sem nenhuma falta não aparece em regra_3_5: vale como completo (coalesce acima).
    left join (
        select
            *,
            dias_sem_temperatura <= 5 and maior_sequencia_sem_temperatura <= 3
                as temperatura_valida,
            dias_sem_umidade <= 5 and maior_sequencia_sem_umidade <= 3 as umidade_valida,
            dias_sem_chuva_medida <= 5 and maior_sequencia_sem_chuva <= 3 as chuva_valida
        from regra_3_5
    ) as r using (estacao_id, mes_referencia)
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
    d.dias_provisorios,
    d.dias_sem_temperatura,
    d.maior_sequencia_sem_temperatura,
    d.dias_sem_chuva_medida,
    d.maior_sequencia_sem_chuva,
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
