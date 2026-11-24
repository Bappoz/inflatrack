-- Clima por praça do IPCA x mês: as variáveis climáticas da matriz de treino do modelo preditivo
-- (PLAN_E3_E4.md, Seções 1.3 e 5.3). Encontra fct_inflacao_mensal por
-- (codigo_localidade, mes_referencia). O Brasil (1) não entra: não há estação nacional, e a média
-- de 16 capitais não é o clima de onde o alimento é plantado.
--
-- Grade completa: cada praça tem todos os meses entre o seu primeiro e o seu último com dado, para
-- que os lags sejam sempre "k meses antes" e nunca "k linhas antes". Os lags são calculados aqui,
-- sobre a série da praça, depois de juntar as estações dela (hoje uma por praça).
--
-- Sem vazamento: toda coluna de um mês usa só aquele mês e os anteriores (normais climatológicas
-- vêm só de anos anteriores, ver int_clima__anomalia_mensal). mes_fechado diz se o INMET já
-- publicou o mês inteiro daquela praça; o mês em curso não deve entrar no treino.
--
-- Clima provisório: os dias que o INMET ainda não publicou vêm do Open-Meteo (modelo em grade) e
-- são contados em dias_provisorios. mes_fechado olha só o dado oficial, então um mês com dia
-- provisório nunca está fechado. Para prever o mês corrente, use o provisório; para treinar, não.

with estacao_mes as (
    select a.*, spi.precipitacao_3m_mm, spi.spi_3
    from {{ ref('int_clima__anomalia_mensal') }} as a
    left join {{ ref('int_clima__spi_mensal') }} as spi using (estacao_id, mes_referencia)
    where a.codigo_localidade is not null
),

-- Último dia publicado pelo INMET em cada praça (só o oficial): uma estação parada não fecha o
-- mês por causa das outras, e o provisório não fecha mês nenhum.
ultima_leitura as (
    select
        mapa.codigo_localidade,
        max(d.data_referencia) filter (where d.observado) as data_referencia
    from {{ ref('stg_clima__medicao_diaria') }} as d
    inner join {{ ref('seed_de_para_estacao_localidade') }} as mapa using (estacao_id)
    group by mapa.codigo_localidade
),

localidade_mes as (
    select
        codigo_localidade,
        mes_referencia,
        count(*) filter (where dias_com_registro > 0) as estacoes_com_dado,
        avg(temp_media) as temp_media,
        min(temp_min_absoluta) as temp_min_absoluta,
        max(temp_max_absoluta) as temp_max_absoluta,
        avg(temp_media_anomalia) as temp_media_anomalia,
        avg(precipitacao_total_mm) as precipitacao_total_mm,
        avg(precipitacao_anomalia_mm) as precipitacao_anomalia_mm,
        avg(dias_com_chuva) as dias_com_chuva,
        avg(umidade_relativa_media_pct) as umidade_relativa_media_pct,
        avg(precipitacao_3m_mm) as precipitacao_3m_mm,
        avg(spi_3) as spi_3,
        max(dias_com_registro) as dias_com_registro,
        max(dias_provisorios) as dias_provisorios
    from estacao_mes
    group by codigo_localidade, mes_referencia
),

grade as (
    select l.codigo_localidade, c.mes_referencia
    from (
        select codigo_localidade, min(mes_referencia) as primeiro, max(mes_referencia) as ultimo
        from estacao_mes
        group by codigo_localidade
    ) as l
    inner join {{ ref('dim_calendario') }} as c
        on c.mes_referencia between l.primeiro and l.ultimo
),

serie as (
    select
        g.codigo_localidade,
        g.mes_referencia,
        coalesce(m.estacoes_com_dado, 0) as estacoes_com_dado,
        coalesce(m.dias_com_registro, 0) as dias_com_registro,
        coalesce(m.dias_provisorios, 0) as dias_provisorios,
        day(last_day(g.mes_referencia)) as dias_no_mes,
        m.temp_media,
        m.temp_min_absoluta,
        m.temp_max_absoluta,
        m.temp_media_anomalia,
        m.precipitacao_total_mm,
        m.precipitacao_anomalia_mm,
        m.dias_com_chuva,
        m.umidade_relativa_media_pct,
        m.precipitacao_3m_mm,
        m.spi_3
    from grade as g
    left join localidade_mes as m using (codigo_localidade, mes_referencia)
)

select
    s.codigo_localidade,
    s.mes_referencia,
    coalesce(last_day(s.mes_referencia) <= u.data_referencia, false) as mes_fechado,
    s.estacoes_com_dado,
    s.dias_com_registro,
    s.dias_provisorios,
    s.dias_no_mes,
    {{ colunas_clima_mensal('s') }}
from serie as s
inner join ultima_leitura as u using (codigo_localidade)
window w as (partition by s.codigo_localidade order by s.mes_referencia)
