-- Fato do comerciante: uma linha por produto do lojista x mês. Compara, lado a lado, o preço que
-- ele praticou e a inflação oficial do subitem do produto na praça dele (pergunta 5).
--
-- Janela de comparação: o preço de 12 meses atrás contra as 12 variações seguintes do IPCA, ou o
-- preço do cadastro contra as variações desde então, se o produto for mais novo. A variação do
-- mês do cadastro não conta, porque o preço já foi definido naquele mês.
--
-- Num mês ainda não publicado pelo IBGE, a janela fica parada no último mês publicado
-- (`mes_ipca_referencia`): a inflação de 12 meses até lá contra o preço de 12 meses antes dele. Sem
-- isso, a janela perderia o mês mais antigo sem ganhar o novo, e o mês corrente, o mais consultado,
-- subestimaria a inflação.

with mensal as (
    select * from {{ ref('int_transacional__mensal') }}
),

ipca as (
    select codigo_categoria, codigo_localidade, mes_referencia, variacao_mensal_pct
    from {{ ref('fct_inflacao_mensal') }}
    where indice = 'IPCA'
),

-- Nem todo subitem é medido em toda praça. O Brasil entra no lugar, e a coluna deixa isso claro.
com_ipca as (
    select
        m.*,
        coalesce(local.variacao_mensal_pct, brasil.variacao_mensal_pct) as ipca_mensal_pct,
        case
            when local.variacao_mensal_pct is not null then 'local'
            when brasil.variacao_mensal_pct is not null then 'brasil'
        end as origem_ipca,
        row_number() over (partition by m.id_produto order by m.mes_referencia) as ordem
    from mensal as m
    left join ipca as local
        on local.codigo_categoria = m.codigo_subitem_ipca
        and local.codigo_localidade = m.codigo_localidade
        and local.mes_referencia = m.mes_referencia
    left join ipca as brasil
        on brasil.codigo_categoria = m.codigo_subitem_ipca
        and brasil.codigo_localidade = 1
        and brasil.mes_referencia = m.mes_referencia
),

janelas as (
    select
        *,
        max(mes_referencia) filter (ipca_mensal_pct is not null) over produto_ate_aqui
            as mes_ipca_referencia,
        lag(preco_brl) over produto as preco_mes_anterior,
        first_value(preco_brl) over ate_12m_atras as preco_base_no_mes,
        first_value(custo_brl) over ate_12m_atras as custo_base_no_mes,
        coalesce(
            exp(sum(
                case when ordem > 1 then ln(1 + cast(ipca_mensal_pct as double) / 100) end
            ) over ultimos_12m),
            1
        ) as fator_ipca_12m_no_mes,
        coalesce(
            exp(sum(
                case when ordem > 1 then ln(1 + cast(ipca_mensal_pct as double) / 100) end
            ) over produto_ate_aqui),
            1
        ) as fator_ipca_desde_cadastro
    from com_ipca
    window
        produto as (partition by id_produto order by mes_referencia),
        produto_ate_aqui as (produto rows between unbounded preceding and current row),
        ate_12m_atras as (produto rows between 12 preceding and current row),
        ultimos_12m as (produto rows between 11 preceding and current row)
),

-- Só o mês com variação publicada (ou o do cadastro) move a janela; os outros repetem a última.
janela_publicada as (
    select
        *,
        last_value(fator_ipca_12m_no_mes ignore nulls) over parado as fator_ipca_12m,
        last_value(preco_base_no_mes ignore nulls) over parado as preco_base,
        last_value(custo_base_no_mes ignore nulls) over parado as custo_base
    from (
        select
            * exclude (fator_ipca_12m_no_mes, preco_base_no_mes, custo_base_no_mes),
            case when ordem = 1 or ipca_mensal_pct is not null then fator_ipca_12m_no_mes end
                as fator_ipca_12m_no_mes,
            case when ordem = 1 or ipca_mensal_pct is not null then preco_base_no_mes end
                as preco_base_no_mes,
            case when ordem = 1 or ipca_mensal_pct is not null then custo_base_no_mes end
                as custo_base_no_mes
        from janelas
    )
    window parado as (
        partition by id_produto
        order by mes_referencia
        rows between unbounded preceding and current row
    )
),

metricas as (
    select
        *,
        cast(preco_brl as double) / nullif(cast(preco_base as double), 0) as fator_preco_12m,
        fator_ipca_12m * cast(preco_base as double) / nullif(cast(preco_brl as double), 0) - 1
            as defasagem
    from janela_publicada
)

select
    m.id_produto,
    m.mes_referencia,
    d.id_versao_preco,
    m.id_lojista,
    m.hash_estabelecimento,
    m.codigo_localidade,
    m.codigo_subitem_ipca,
    m.preco_brl,
    m.custo_brl,
    m.quantidade_vendida,
    m.receita_brl,
    cast(round(100 * (m.preco_brl - m.custo_brl) / nullif(m.preco_brl, 0), 4) as decimal(12, 4))
        as margem_pct,
    cast(
        round(100 * (m.preco_brl - m.preco_mes_anterior) / nullif(m.preco_mes_anterior, 0), 4)
        as decimal(12, 4)
    ) as variacao_preco_mensal_pct,
    cast(m.ipca_mensal_pct as decimal(12, 4)) as ipca_mensal_pct,
    m.origem_ipca,
    m.mes_ipca_referencia,
    cast(round(100 * (m.fator_preco_12m - 1), 4) as decimal(12, 4)) as variacao_preco_12m_pct,
    cast(round(100 * (m.custo_brl - m.custo_base) / nullif(m.custo_base, 0), 4) as decimal(12, 4))
        as variacao_custo_12m_pct,
    cast(round(100 * (m.fator_ipca_12m - 1), 4) as decimal(12, 4)) as ipca_acum_12m_pct,
    cast(round(100 * (m.fator_ipca_desde_cadastro - 1), 4) as decimal(12, 4))
        as ipca_acum_desde_cadastro_pct,
    cast(round(100 * m.defasagem, 4) as decimal(12, 4)) as defasagem_12m_pct,
    cast(round(100 * greatest(m.defasagem, 0), 4) as decimal(12, 4)) as reajuste_minimo_pct
from metricas as m
-- A versão vigente no fim do mês é a última que começou antes dele. Vale também no mês da exclusão.
asof left join {{ ref('dim_produto_preco_scd2') }} as d
    on m.id_produto = d.id_produto
    and timezone('America/Sao_Paulo', cast(m.mes_referencia + interval 1 month as timestamp))
        > d.vigencia_inicio
