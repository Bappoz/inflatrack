-- Fato central: uma linha por índice x categoria da cesta x localidade x mês. Só dado público do
-- IBGE: produto de lojista nunca entra aqui (PLAN_E3_E4.md, Seção 2.2), e as demais fontes se
-- encontram com esta tabela por mes_referencia, via dim_calendario.

with mensal as (
    select * from {{ ref('int_ipca__mensal') }}
)

select
    m.indice,
    m.codigo_categoria,
    m.codigo_localidade,
    m.mes_referencia,
    c.id_versao_cesta,
    c.nivel_categoria,
    m.agregado_origem,
    m.variacao_mensal_pct,
    m.variacao_acum_ano_pct,
    m.variacao_acum_12m_pct,
    m.origem_acum_12m,
    m.peso_mensal_pct,
    m.numero_indice,
    m.media_movel_3m_pct,
    m.media_movel_6m_pct,
    m.media_movel_12m_pct,
    m.desvio_padrao_12m_pct,
    m.variacao_mensal_lag_1m_pct,
    m.variacao_mensal_lag_2m_pct,
    m.variacao_mensal_lag_3m_pct
from mensal as m
left join {{ ref('dim_cesta_ipca_scd2') }} as c
    on c.indice = m.indice
    and c.codigo_categoria = m.codigo_categoria
    and m.mes_referencia >= c.vigencia_inicio
    and (c.vigencia_fim is null or m.mes_referencia < c.vigencia_fim)
