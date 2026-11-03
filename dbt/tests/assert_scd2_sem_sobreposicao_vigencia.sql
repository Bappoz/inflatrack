-- Um subitem da cesta ou um produto do lojista nunca tem duas faixas de vigência ao mesmo tempo,
-- e no máximo uma aberta.
with cesta as (
    select indice || '-' || codigo_categoria as entidade, vigencia_inicio as inicio, vigencia_fim as fim
    from {{ ref('dim_cesta_ipca_scd2') }}
),

produto as (
    select cast(id_produto as varchar) as entidade, vigencia_inicio as inicio, vigencia_fim as fim
    from {{ ref('dim_produto_preco_scd2') }}
),

sobreposicoes_cesta as (
    select a.entidade, 'cesta' as dimensao
    from cesta as a
    inner join cesta as b
        on a.entidade = b.entidade
        and a.inicio < b.inicio
        and (a.fim is null or a.fim > b.inicio)
),

sobreposicoes_produto as (
    select a.entidade, 'produto' as dimensao
    from produto as a
    inner join produto as b
        on a.entidade = b.entidade
        and a.inicio < b.inicio
        and (a.fim is null or a.fim > b.inicio)
)

select * from sobreposicoes_cesta
union all
select * from sobreposicoes_produto
