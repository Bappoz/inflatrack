-- Metabase, pergunta 5 do projeto: "Quanto preciso reajustar cada produto para não perder margem
-- para a inflação?" Uma linha por produto do lojista, no último mês calculado: o preço, quanto ele
-- subiu em 12 meses, o IPCA do subitem na mesma janela, a defasagem e o reajuste mínimo.
--
-- Lê só a vitrine `serie`. Tudo vem pronto da Gold (gold.fct_reajuste_lojista e
-- gold.dim_produto_preco_scd2); nada é calculado aqui. defasagem_12m_pct positiva = preço abaixo
-- da inflação do subitem; reajuste_minimo_pct é o reajuste que recupera a defasagem (zero se o
-- preço já acompanhou). origem_ipca diz se o IPCA é da praça do lojista ou o nacional.
--
-- Este painel é a visão interna da Squad (todas as lojas). Cada lojista vendo só os próprios
-- produtos depende do RLS da E4 (Lucas, Seção 5.1). A projeção do próximo mês
-- (recomendacao_reajuste) também é E4.
with ultimo_mes as (
    select id_produto, max(mes_referencia) as mes
    from serie.fct_reajuste_lojista
    group by id_produto
)
select
    p.nome_produto as produto,
    r.id_lojista,
    r.codigo_subitem_ipca,
    (
        select c.nome_categoria
        from serie.dim_cesta_ipca_scd2 c
        where c.indice = 'IPCA' and c.codigo_categoria = r.codigo_subitem_ipca
        order by c.vigencia_inicio desc
        limit 1
    ) as subitem_ipca,
    r.preco_brl,
    r.variacao_preco_12m_pct,
    r.ipca_acum_12m_pct,
    r.origem_ipca,
    r.defasagem_12m_pct,
    r.reajuste_minimo_pct,
    to_char(r.mes_ipca_referencia, 'MM/YYYY') as ipca_ate_o_mes
from serie.fct_reajuste_lojista r
join ultimo_mes u on u.id_produto = r.id_produto and u.mes = r.mes_referencia
join serie.dim_produto_preco_scd2 p on p.id_versao_preco = r.id_versao_preco
order by r.reajuste_minimo_pct desc nulls last, p.nome_produto;
