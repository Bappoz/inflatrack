-- Câmbio x juros x inflação, um mês por linha (PLAN_E3_E4.md, Seção 5.2: pressão
-- macroeconômica sobre a inflação). A Silver de Dólar/Selic e o IPCA da Gold se encontram
-- pela dim_calendario (Seção 6.1).
--
-- juro_real_12m_pct = Selic acumulada em 12 meses descontada do IPCA de 12 meses (Fisher):
-- juro real alto segura preço; dólar subindo empurra preço de importado e commodity.

with macro as (
    select * from {{ ref('int_macroeconomia__mensal') }}
),

selic_12m as (
    -- Produto dos 12 fatores mensais; só sai quando há 12 meses na janela.
    select
        mes_referencia,
        case
            when count(selic_acumulada_mes_pct) over w = 12
                then (exp(sum(ln(1 + selic_acumulada_mes_pct / 100)) over w) - 1) * 100
        end as selic_acumulada_12m
    from macro
    window w as (order by mes_referencia rows between 11 preceding and current row)
),

ipca_brasil as (
    select mes_referencia, variacao_acum_12m_pct as ipca_12m
    from {{ ref('fct_inflacao_mensal') }}
    where indice = 'IPCA' and nivel_categoria = 'geral' and codigo_localidade = 1
),

meses as (
    select c.mes_referencia
    from {{ ref('dim_calendario') }} as c
    where c.mes_referencia between (select min(mes_referencia) from macro)
        and (select max(mes_referencia) from macro)
)

select
    m.mes_referencia,
    x.mes_fechado,

    -- câmbio
    x.dolar_media,
    x.dolar_fechamento,
    x.dolar_var_mensal_pct,
    x.dolar_var_12m_pct,
    x.dolar_volatilidade_12m_pct,

    -- juros
    x.selic_anualizada_fim_mes_pct,
    x.selic_acumulada_mes_pct,
    cast(round(s.selic_acumulada_12m, 4) as decimal(12, 4)) as selic_acumulada_12m_pct,

    -- inflação e juro real
    cast(i.ipca_12m as decimal(12, 4)) as ipca_12m_pct,
    cast(round(
        ((1 + s.selic_acumulada_12m / 100) / (1 + i.ipca_12m / 100) - 1) * 100, 4
    ) as decimal(12, 4)) as juro_real_12m_pct

from meses as m
left join macro as x using (mes_referencia)
left join selic_12m as s using (mes_referencia)
left join ipca_brasil as i using (mes_referencia)
