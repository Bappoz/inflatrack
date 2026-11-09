-- Commodities no grão mensal (PLAN_E3_E4.md, Seções 1.3 e 5.0.1). Uma linha por symbol x mês,
-- formato longo, todas as métricas da própria fonte na mesma linha (decisão de 2026-10-29).
--
-- * Séries diárias (WTI, BRENT, NATURAL_GAS): média, fechamento, mínimo, máximo e desvio
--   intramês dos pregões observados.
-- * Séries mensais: um valor por mês, então média = fechamento e não há desvio intramês.
-- * Para todas, sobre a média do mês: variações, médias móveis de 3/6/12 meses e a
--   volatilidade (desvio móvel da variação mensal). As janelas só olham para trás.
-- * Os meses vão do primeiro ao último mês com preço, sem buraco: mês sem nenhum pregão
--   observado fica com média NULL, em vez de sumir.

with diario as (
    select * from {{ ref('stg_commodities__cotacao') }}
),

-- Um mês está fechado quando a coleta aconteceu depois do fim dele. O mês corrente das
-- séries diárias (coletadas no meio do mês) entra como mes_fechado = false.
coleta as (
    select symbol, cast(max(_ingerido_em) as date) as coletado_em
    from diario
    group by 1
),

agregado as (
    select
        symbol,
        any_value(intervalo) as intervalo,
        cast(date_trunc('month', data_referencia) as date) as mes_referencia,
        avg(preco) as media,
        arg_max(preco, data_referencia) filter (where observado) as fechamento,
        min(preco) as minimo,
        max(preco) as maximo,
        stddev_samp(preco) as desvio_intramensal,
        count(*) filter (where observado) as dias_observados,
        count(*) as registros_na_origem
    from diario
    group by symbol, mes_referencia
),

limites as (
    select symbol, min(mes_referencia) as primeiro_mes, max(mes_referencia) as ultimo_mes
    from agregado
    where dias_observados > 0
    group by 1
),

grade as (
    select l.symbol, cast(g.mes as date) as mes_referencia
    from limites as l,
        generate_series(l.primeiro_mes, l.ultimo_mes, interval 1 month) as g(mes)
),

mensal as (
    select
        g.symbol,
        g.mes_referencia,
        coalesce(a.dias_observados, 0) as dias_observados,
        coalesce(a.registros_na_origem, 0) as registros_na_origem,
        a.media,
        a.fechamento,
        a.minimo,
        a.maximo,
        a.desvio_intramensal,
        last_day(g.mes_referencia) < c.coletado_em as mes_fechado
    from grade as g
    left join agregado as a using (symbol, mes_referencia)
    inner join coleta as c using (symbol)
),

variacoes as (
    select
        *,
        100 * (media / nullif(lag(media, 1) over w, 0) - 1) as var_mensal,
        100 * (media / nullif(lag(media, 12) over w, 0) - 1) as var_12m,
        avg(media) over (w rows between 2 preceding and current row) as mm3,
        avg(media) over (w rows between 5 preceding and current row) as mm6,
        avg(media) over (w rows between 11 preceding and current row) as mm12
    from mensal
    window w as (partition by symbol order by mes_referencia)
),

volatilidade as (
    select
        *,
        stddev_samp(var_mensal) over (w rows between 11 preceding and current row)
            as desvio_movel_12m,
        -- Referência do z-score: os 12 meses ANTERIORES, para o próprio mês não diluir o choque.
        avg(var_mensal) over (w rows between 12 preceding and 1 preceding) as media_var_12m_anteriores,
        stddev_samp(var_mensal) over (w rows between 12 preceding and 1 preceding)
            as desvio_var_12m_anteriores
    from variacoes
    window w as (partition by symbol order by mes_referencia)
)

select
    v.symbol,
    v.mes_referencia,
    cat.intervalo,
    v.mes_fechado,
    v.dias_observados,
    v.registros_na_origem,
    cast(v.media as decimal(18, 6)) as media,
    cast(v.fechamento as decimal(18, 6)) as fechamento,
    cast(v.minimo as decimal(18, 6)) as minimo,
    cast(v.maximo as decimal(18, 6)) as maximo,
    cast(v.desvio_intramensal as decimal(18, 6)) as desvio_intramensal,
    cast(round(v.var_mensal, 4) as decimal(12, 4)) as var_mensal_pct,
    cast(round(v.var_12m, 4) as decimal(12, 4)) as var_12m_pct,
    cast(v.mm3 as decimal(18, 6)) as mm3,
    cast(v.mm6 as decimal(18, 6)) as mm6,
    cast(v.mm12 as decimal(18, 6)) as mm12,
    cast(round(v.desvio_movel_12m, 4) as decimal(12, 4)) as desvio_movel_12m_pct,
    cast(round(
        (v.var_mensal - v.media_var_12m_anteriores) / nullif(v.desvio_var_12m_anteriores, 0), 4
    ) as decimal(12, 4)) as z_score_var_mensal,
    coalesce(
        (v.var_mensal - v.media_var_12m_anteriores)
        / nullif(v.desvio_var_12m_anteriores, 0) >= 2,
        false
    ) as alta_forte
from volatilidade as v
inner join {{ ref('seed_commodity_catalogo') }} as cat using (symbol)
