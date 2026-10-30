-- PIB trimestral no grão mensal (PLAN_E3_E4.md, Seção 1.3 item 2). Uma linha por setor x mês.
--
-- Bloco PAINEL: o mês mostra o trimestre a que pertence (abr/mai/jun -> 2T).
-- Bloco MODELO: o mês só enxerga trimestres já publicados. O IBGE divulga cerca de
-- 2 meses depois do fim do trimestre; o trimestre conta como disponível a partir do
-- 3º mês após o fim (2T, abr-jun -> setembro), ou seja, trimestre_inicio + 5 meses.

{% set meses_ate_divulgar = 5 %}

with trimestres as (
    select
        codigo_setor,
        trimestre_inicio,
        valor_milhoes_brl,
        lag(valor_milhoes_brl, 4) over (
            partition by codigo_setor order by trimestre_inicio
        ) as valor_ano_anterior
    from {{ ref('stg_pib__valor') }}
),

pib_total as (
    select trimestre_inicio, valor_milhoes_brl as pib
    from trimestres
    where codigo_setor = '90707'  -- PIB a preços de mercado
),

trimestres_com_metricas as (
    select
        t.codigo_setor,
        t.trimestre_inicio,
        t.valor_milhoes_brl,
        cast(round(
            100 * (t.valor_milhoes_brl - t.valor_ano_anterior)
            / nullif(t.valor_ano_anterior, 0),
            4
        ) as decimal(12, 4)) as var_anual_pct,
        cast(round(100 * t.valor_milhoes_brl / nullif(p.pib, 0), 4) as decimal(12, 4))
            as participacao_pib_pct,
        cast(t.trimestre_inicio + interval {{ meses_ate_divulgar }} month as date)
            as disponivel_em
    from trimestres as t
    left join pib_total as p using (trimestre_inicio)
),

-- Os meses vão do primeiro trimestre até o último mês em que o trimestre mais recente
-- ainda é o último divulgado (o seguinte sai 3 meses depois), sem passar do mês atual.
limites as (
    select
        min(trimestre_inicio) as primeiro_mes,
        least(
            cast(max(trimestre_inicio) + interval {{ meses_ate_divulgar + 2 }} month as date),
            cast(date_trunc('month', current_date) as date)
        ) as ultimo_mes
    from trimestres_com_metricas
),

meses as (
    select cast(mes as date) as mes_referencia
    from limites, generate_series(primeiro_mes, ultimo_mes, interval 1 month) as g(mes)
),

setores as (
    select distinct codigo_setor from trimestres_com_metricas
),

grade as (
    select
        s.codigo_setor,
        m.mes_referencia,
        cast(date_trunc('quarter', m.mes_referencia) as date) as trimestre_referencia,
        cast(
            date_trunc('quarter', m.mes_referencia - interval {{ meses_ate_divulgar }} month)
            as date
        ) as trimestre_ultimo_divulgado
    from setores as s
    cross join meses as m
)

select
    g.mes_referencia,
    g.codigo_setor,

    -- painel
    g.trimestre_referencia,
    ref.valor_milhoes_brl as valor_trimestre_referencia,
    ref.var_anual_pct,
    ref.participacao_pib_pct,
    ref.disponivel_em as trimestre_referencia_disponivel_em,

    -- modelo
    g.trimestre_ultimo_divulgado,
    ult.valor_milhoes_brl as valor_ultimo_divulgado,
    pen.valor_milhoes_brl as valor_penultimo_divulgado,
    ant.valor_milhoes_brl as valor_antepenultimo_divulgado,
    ult.var_anual_pct as var_anual_pct_ultimo_divulgado

from grade as g
left join trimestres_com_metricas as ref
    on ref.codigo_setor = g.codigo_setor
    and ref.trimestre_inicio = g.trimestre_referencia
left join trimestres_com_metricas as ult
    on ult.codigo_setor = g.codigo_setor
    and ult.trimestre_inicio = g.trimestre_ultimo_divulgado
left join trimestres_com_metricas as pen
    on pen.codigo_setor = g.codigo_setor
    and pen.trimestre_inicio = cast(g.trimestre_ultimo_divulgado - interval 3 month as date)
left join trimestres_com_metricas as ant
    on ant.codigo_setor = g.codigo_setor
    and ant.trimestre_inicio = cast(g.trimestre_ultimo_divulgado - interval 6 month as date)
