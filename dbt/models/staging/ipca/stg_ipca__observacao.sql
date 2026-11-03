-- Uma linha por agregado x localidade x variável x categoria x mês, na versão mais recente que o
-- IBGE publicou. A Bronze guarda todas as versões; a escolha da última é daqui (ADR 0001).
--
-- Os marcadores continuam (valor nulo, texto em valor_bruto): o grão da fonte é mantido. O SIDRA
-- identifica a categoria pelo id interno; a tradução para o código da cesta usa os metadados do
-- próprio agregado. O 1737 não tem classificação: é sempre o índice geral (7169).

with versoes as (
    select
        *,
        row_number() over janela as ordem_versao,
        count(*) over janela_inteira as versoes_coletadas
    from {{ source('bronze_ipca', 'ipca_observacao') }}
    window
        janela as (
            partition by agregado, mes_referencia, codigo_localidade, codigo_variavel, id_categoria
            order by _ingerido_em desc, _id_resposta desc
        ),
        janela_inteira as (
            partition by agregado, mes_referencia, codigo_localidade, codigo_variavel, id_categoria
        )
),

cesta as (
    select agregado, id_categoria, codigo_categoria
    from {{ ref('stg_ipca__metadados') }}
    where versao_atual
)

select
    cast(v.agregado as smallint) as agregado,
    v.mes_referencia,
    v.codigo_localidade,
    v.codigo_variavel,
    v.id_categoria,
    case when v.agregado = 1737 then '7169' else c.codigo_categoria end as codigo_categoria,
    cast(v.valor as decimal(28, 13)) as valor,
    v.valor_bruto,
    v.valor is not null as observado,
    v.versoes_coletadas,
    v._ingerido_em
from versoes as v
left join cesta as c
    on c.agregado = v.agregado
    and c.id_categoria = v.id_categoria
where v.ordem_versao = 1
