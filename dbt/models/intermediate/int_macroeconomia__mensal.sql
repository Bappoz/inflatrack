-- Macroeconomia no grão mensal (PLAN_E3_E4.md, Seções 1.2, 1.3 e 5.0.1).
-- Consolida Câmbio Comercial PTAX (Dólar) e Juros Básicos (Taxa Selic) no grão
-- mes_referencia = YYYY-MM-01.
--
-- Dólar: média mensal da venda, fechamento oficial, mínimo, máximo, desvio intramês,
--        spread médio, variações (mensal e 12m), médias móveis (3, 6 e 12m) e volatilidade.
-- Selic: taxa acumulada real do mês (capitalização composta exata), taxa anualizada do
--        fim do mês (meta Copom), variações em pontos percentuais e médias móveis.

with dolar_diario as (
    select
        data_referencia,
        cast(date_trunc('month', data_referencia) as date) as mes_referencia,
        cotacao_compra,
        cotacao_venda,
        spread_fechamento
    from {{ ref('stg_dolar__cotacao_diaria') }}
),

selic_diaria as (
    select
        data_referencia,
        cast(date_trunc('month', data_referencia) as date) as mes_referencia,
        taxa_dia_pct,
        taxa_anualizada_pct,
        fator_diario
    from {{ ref('stg_selic__taxa_diaria') }}
),

dolar_mensal as (
    select
        mes_referencia,
        count(*) as dias_uteis_dolar,
        avg(cotacao_venda) as dolar_media,
        arg_max(cotacao_venda, data_referencia) as dolar_fechamento,
        min(cotacao_venda) as dolar_minimo,
        max(cotacao_venda) as dolar_maximo,
        stddev_samp(cotacao_venda) as dolar_desvio_intramensal,
        avg(spread_fechamento) as spread_medio
    from dolar_diario
    group by mes_referencia
),

selic_mensal as (
    select
        mes_referencia,
        count(*) as dias_uteis_selic,
        avg(taxa_dia_pct) as selic_media_dia_pct,
        arg_max(taxa_anualizada_pct, data_referencia) as selic_anualizada_fim_mes_pct,
        (product(fator_diario) - 1.0) * 100.0 as selic_acumulada_mes_pct
    from selic_diaria
    group by mes_referencia
),

combinado as (
    select
        coalesce(d.mes_referencia, s.mes_referencia) as mes_referencia,
        coalesce(d.dias_uteis_dolar, 0) as dias_uteis_dolar,
        coalesce(s.dias_uteis_selic, 0) as dias_uteis_selic,
        d.dolar_media,
        d.dolar_fechamento,
        d.dolar_minimo,
        d.dolar_maximo,
        d.dolar_desvio_intramensal,
        d.spread_medio,
        s.selic_media_dia_pct,
        s.selic_anualizada_fim_mes_pct,
        s.selic_acumulada_mes_pct,
        last_day(coalesce(d.mes_referencia, s.mes_referencia)) < current_date as mes_fechado
    from dolar_mensal as d
    full outer join selic_mensal as s using (mes_referencia)
),

variacoes as (
    select
        *,
        -- Variações percentuais do Dólar
        100.0 * (dolar_media / nullif(lag(dolar_media, 1) over w, 0) - 1.0) as dolar_var_mensal,
        100.0 * (dolar_media / nullif(lag(dolar_media, 12) over w, 0) - 1.0) as dolar_var_12m,
        avg(dolar_media) over (w rows between 2 preceding and current row) as dolar_mm3,
        avg(dolar_media) over (w rows between 5 preceding and current row) as dolar_mm6,
        avg(dolar_media) over (w rows between 11 preceding and current row) as dolar_mm12,

        -- Variações e Médias Móveis da Selic Anualizada
        selic_anualizada_fim_mes_pct - lag(selic_anualizada_fim_mes_pct, 1) over w as selic_var_mensal_pontos,
        selic_anualizada_fim_mes_pct - lag(selic_anualizada_fim_mes_pct, 12) over w as selic_var_12m_pontos,
        avg(selic_anualizada_fim_mes_pct) over (w rows between 2 preceding and current row) as selic_mm3_anualizada,
        avg(selic_anualizada_fim_mes_pct) over (w rows between 5 preceding and current row) as selic_mm6_anualizada,
        avg(selic_anualizada_fim_mes_pct) over (w rows between 11 preceding and current row) as selic_mm12_anualizada
    from combinado
    window w as (order by mes_referencia)
),

volatilidade as (
    select
        *,
        stddev_samp(dolar_var_mensal) over (w rows between 11 preceding and current row) as dolar_desvio_movel_12m
    from variacoes
    window w as (order by mes_referencia)
)

select
    mes_referencia,
    mes_fechado,
    dias_uteis_dolar,
    dias_uteis_selic,

    -- Dólar
    cast(dolar_media as decimal(10, 4)) as dolar_media,
    cast(dolar_fechamento as decimal(10, 4)) as dolar_fechamento,
    cast(dolar_minimo as decimal(10, 4)) as dolar_minimo,
    cast(dolar_maximo as decimal(10, 4)) as dolar_maximo,
    cast(dolar_desvio_intramensal as decimal(10, 4)) as dolar_desvio_intramensal,
    cast(spread_medio as decimal(10, 4)) as spread_medio,
    cast(round(dolar_var_mensal, 4) as decimal(12, 4)) as dolar_var_mensal_pct,
    cast(round(dolar_var_12m, 4) as decimal(12, 4)) as dolar_var_12m_pct,
    cast(dolar_mm3 as decimal(10, 4)) as dolar_mm3,
    cast(dolar_mm6 as decimal(10, 4)) as dolar_mm6,
    cast(dolar_mm12 as decimal(10, 4)) as dolar_mm12,
    cast(round(dolar_desvio_movel_12m, 4) as decimal(12, 4)) as dolar_volatilidade_12m_pct,

    -- Selic
    cast(selic_media_dia_pct as decimal(10, 6)) as selic_media_dia_pct,
    cast(selic_anualizada_fim_mes_pct as decimal(10, 4)) as selic_anualizada_fim_mes_pct,
    cast(selic_acumulada_mes_pct as decimal(10, 4)) as selic_acumulada_mes_pct,
    cast(round(selic_var_mensal_pontos, 4) as decimal(10, 4)) as selic_var_mensal_pontos,
    cast(round(selic_var_12m_pontos, 4) as decimal(10, 4)) as selic_var_12m_pontos,
    cast(selic_mm3_anualizada as decimal(10, 4)) as selic_mm3_anualizada,
    cast(selic_mm6_anualizada as decimal(10, 4)) as selic_mm6_anualizada,
    cast(selic_mm12_anualizada as decimal(10, 4)) as selic_mm12_anualizada
from volatilidade
