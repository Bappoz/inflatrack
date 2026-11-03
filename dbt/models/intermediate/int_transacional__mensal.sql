-- Dados do lojista no grão mensal. Uma linha por produto x mês, do mês do cadastro até o mês atual
-- ou o mês da exclusão. O preço e o custo são os vigentes no fim do mês; o mês é o de Brasília,
-- para o resultado não depender do fuso da máquina que roda o dbt.

with eventos as (
    select * from {{ ref('int_transacional__precos') }}
),

limites as (
    select
        id_produto,
        min(efetivo_em) filter (not excluido) as primeiro_evento,
        min(efetivo_em) filter (excluido) as excluido_em
    from eventos
    group by id_produto
),

meses as (
    select
        l.id_produto,
        cast(mes as date) as mes_referencia,
        -- Primeiro instante do mês seguinte, em Brasília: o preço do mês é o último antes dele.
        timezone('America/Sao_Paulo', cast(mes + interval 1 month as timestamp)) as fim_do_mes
    from limites as l,
        generate_series(
            date_trunc('month', timezone('America/Sao_Paulo', l.primeiro_evento)),
            date_trunc(
                'month',
                timezone('America/Sao_Paulo', coalesce(l.excluido_em, current_timestamp))
            ),
            interval 1 month
        ) as g(mes)
),

no_fim_do_mes as (
    select
        m.id_produto,
        m.mes_referencia,
        e.id_lojista,
        e.nome_produto,
        e.codigo_subitem_ipca,
        e.preco_centavos,
        e.custo_centavos
    from meses as m
    asof left join eventos as e
        on m.id_produto = e.id_produto
        and m.fim_do_mes > e.efetivo_em
),

-- Corrigir uma venda é inserir outra linha para o mesmo mês: vale a mais recente.
vendas as (
    select
        cast(json_extract_string(depois, '$.id_produto') as bigint) as id_produto,
        cast(json_extract_string(depois, '$.mes_referencia') as date) as mes_referencia,
        cast(json_extract_string(depois, '$.quantidade') as decimal(14, 3)) as quantidade_vendida,
        cast(json_extract_string(depois, '$.receita_centavos') as bigint) as receita_centavos
    from {{ ref('stg_transacional__mudanca') }}
    where tabela = 'venda_mensal' and operacao in ('r', 'I')
    qualify row_number() over (
        partition by id_produto, mes_referencia
        order by cast(json_extract_string(depois, '$.registrado_em') as timestamptz) desc, lsn desc
    ) = 1
),

-- O CNPJ já chega como hash. Mudança de praça vale para o histórico inteiro do lojista: a
-- comparação é sempre com a praça atual dele.
lojistas as (
    select
        id_registro as id_lojista,
        json_extract_string(depois, '$.hash_estabelecimento') as hash_estabelecimento,
        cast(json_extract_string(depois, '$.codigo_localidade') as integer) as codigo_localidade
    from {{ ref('stg_transacional__mudanca') }}
    where tabela = 'lojista' and operacao in ('r', 'I', 'U')
    qualify row_number() over (partition by id_registro order by lsn desc) = 1
)

select
    n.id_produto,
    n.mes_referencia,
    n.id_lojista,
    l.hash_estabelecimento,
    l.codigo_localidade,
    n.codigo_subitem_ipca,
    cast(n.preco_centavos / 100.0 as decimal(14, 2)) as preco_brl,
    cast(n.custo_centavos / 100.0 as decimal(14, 2)) as custo_brl,
    v.quantidade_vendida,
    cast(v.receita_centavos / 100.0 as decimal(14, 2)) as receita_brl
from no_fim_do_mes as n
left join vendas as v using (id_produto, mes_referencia)
left join lojistas as l using (id_lojista)
