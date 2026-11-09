-- IPCA e INPC no grão mensal (PLAN_E3_E4.md, Seção 1.3). Uma linha por índice x categoria x
-- localidade x mês com pelo menos um valor publicado. Une 2938, 1419 e 7060 pelo código da cesta,
-- que é estável entre os agregados; é o 1737 que estende o índice geral (Brasil) até dez/1979.
--
-- As janelas usam `range` e não `rows`: subitens somem e voltam, e 12 linhas seguidas nem sempre
-- são 12 meses seguidos. Uma defasagem só existe se o mês exato existir. Todas olham para trás.
--
-- Materializado como tabela (e não view, como os outros intermediate): são 9 milhões de linhas na
-- origem, e cada teste e modelo abaixo refaria o agrupamento e as janelas.

{{ config(materialized='table') }}

with observacoes as (
    select
        a.indice,
        o.codigo_categoria,
        o.codigo_localidade,
        o.mes_referencia,
        o.agregado,
        v.medida,
        o.valor
    from {{ ref('stg_ipca__observacao') }} as o
    inner join {{ ref('seed_agregado_sidra') }} as a using (agregado)
    inner join {{ ref('seed_variavel_sidra') }} as v using (codigo_variavel)
    where o.observado
),

-- O índice geral do Brasil vem em dois agregados a partir de jul/2006: vale o da estrutura da
-- cesta (2938, 1419, 7060), e o 1737 só preenche o que falta.
meses as (
    select
        indice,
        codigo_categoria,
        codigo_localidade,
        mes_referencia,
        cast(coalesce(min(agregado) filter (agregado <> 1737), 1737) as smallint) as agregado_origem,
        coalesce(
            max(valor) filter (medida = 'variacao_mensal' and agregado <> 1737),
            max(valor) filter (medida = 'variacao_mensal')
        ) as variacao_mensal,
        coalesce(
            max(valor) filter (medida = 'variacao_acum_ano' and agregado <> 1737),
            max(valor) filter (medida = 'variacao_acum_ano')
        ) as variacao_acum_ano,
        coalesce(
            max(valor) filter (medida = 'variacao_acum_12m' and agregado <> 1737),
            max(valor) filter (medida = 'variacao_acum_12m')
        ) as variacao_acum_12m_publicada,
        max(valor) filter (medida = 'peso_mensal') as peso_mensal,
        max(valor) filter (medida = 'numero_indice') as numero_indice
    from observacoes
    group by indice, codigo_categoria, codigo_localidade, mes_referencia
),

com_janelas as (
    select
        *,
        cast(variacao_mensal as double) as variacao,

        -- O agregado 2938 (2006-2011) não publica o acumulado em 12 meses: é produto, não soma.
        exp(sum(ln(1 + cast(variacao_mensal as double) / 100)) over ate_12m) as fator_12m,
        count(variacao_mensal) over ate_12m as meses_em_12m,

        avg(cast(variacao_mensal as double)) over ate_3m as media_3m,
        count(variacao_mensal) over ate_3m as meses_em_3m,
        avg(cast(variacao_mensal as double)) over ate_6m as media_6m,
        count(variacao_mensal) over ate_6m as meses_em_6m,
        avg(cast(variacao_mensal as double)) over ate_12m as media_12m,
        stddev_samp(cast(variacao_mensal as double)) over ate_12m as desvio_12m,

        first_value(variacao_mensal) over ha_1m as variacao_ha_1m,
        first_value(variacao_mensal) over ha_2m as variacao_ha_2m,
        first_value(variacao_mensal) over ha_3m as variacao_ha_3m
    from meses
    window
        serie as (
            partition by indice, codigo_categoria, codigo_localidade
            order by mes_referencia
        ),
        ate_3m as (serie range between interval 2 month preceding and current row),
        ate_6m as (serie range between interval 5 month preceding and current row),
        ate_12m as (serie range between interval 11 month preceding and current row),
        ha_1m as (serie range between interval 1 month preceding and interval 1 month preceding),
        ha_2m as (serie range between interval 2 month preceding and interval 2 month preceding),
        ha_3m as (serie range between interval 3 month preceding and interval 3 month preceding)
)

select
    indice,
    codigo_categoria,
    codigo_localidade,
    mes_referencia,
    agregado_origem,
    cast(variacao_mensal as decimal(12, 4)) as variacao_mensal_pct,
    cast(variacao_acum_ano as decimal(12, 4)) as variacao_acum_ano_pct,
    cast(
        coalesce(
            variacao_acum_12m_publicada,
            case when meses_em_12m = 12 then round(100 * (fator_12m - 1), 4) end
        ) as decimal(12, 4)
    ) as variacao_acum_12m_pct,
    case
        when variacao_acum_12m_publicada is not null then 'publicado'
        when meses_em_12m = 12 then 'calculado'
    end as origem_acum_12m,
    -- Sempre calculado, para conferir a conta contra o que o IBGE publica (teste singular).
    cast(
        case when meses_em_12m = 12 then round(100 * (fator_12m - 1), 4) end as decimal(12, 4)
    ) as variacao_acum_12m_calculada_pct,
    cast(peso_mensal as decimal(12, 4)) as peso_mensal_pct,
    cast(numero_indice as decimal(28, 13)) as numero_indice,
    cast(case when meses_em_3m = 3 then round(media_3m, 4) end as decimal(12, 4))
        as media_movel_3m_pct,
    cast(case when meses_em_6m = 6 then round(media_6m, 4) end as decimal(12, 4))
        as media_movel_6m_pct,
    cast(case when meses_em_12m = 12 then round(media_12m, 4) end as decimal(12, 4))
        as media_movel_12m_pct,
    cast(case when meses_em_12m = 12 then round(desvio_12m, 4) end as decimal(12, 4))
        as desvio_padrao_12m_pct,
    cast(variacao_ha_1m as decimal(12, 4)) as variacao_mensal_lag_1m_pct,
    cast(variacao_ha_2m as decimal(12, 4)) as variacao_mensal_lag_2m_pct,
    cast(variacao_ha_3m as decimal(12, 4)) as variacao_mensal_lag_3m_pct
from com_janelas
