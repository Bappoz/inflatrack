-- Fato da Cesta Básica de Mercado (PROCON):
-- Tabela Gold (Marts / Core) que consolida os preços médios, mínimos, máximos
-- e variações mensais dos produtos essenciais pesquisados na praça do lojista,
-- conectada às dimensões canônicas de tempo (dim_calendario) e espaço (dim_localidade).

with procon as (
    select * from {{ ref('int_procon__mensal') }}
),

calendario as (
    select * from {{ ref('dim_calendario') }}
),

localidade as (
    select * from {{ ref('dim_localidade') }}
)

select
    p.mes_referencia,
    c.ano,
    c.mes,
    coalesce(loc.codigo_localidade, 1) as codigo_localidade,
    coalesce(loc.nome_localidade, p.praca) as nome_praca,
    p.produto as produto_mercado,
    p.unidade,
    p.codigo_subitem_ipca,
    p.preco_medio as preco_medio_mercado,
    p.preco_minimo as preco_minimo_mercado,
    p.preco_maximo as preco_maximo_mercado,
    p.preco_medio_anterior as preco_anterior_mercado,
    p.variacao_mensal_preco_pct as variacao_mensal_mercado_pct
from procon as p
inner join calendario as c
    on c.mes_referencia = p.mes_referencia
left join localidade as loc
    on lower(loc.nome_localidade) = lower(p.praca)
