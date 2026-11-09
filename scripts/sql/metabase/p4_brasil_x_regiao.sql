-- Metabase, pergunta 4 do projeto: "A inflação da minha praça é diferente da do Brasil? E a do
-- INPC, que mede as famílias de renda mais baixa?" Uma linha por localidade do IPCA (Brasil
-- primeiro): o IPCA e o INPC acumulados em 12 meses, índice geral, no último mês divulgado.
--
-- Lê só a vitrine `serie`. Os acumulados vêm prontos da Gold (gold.fct_inflacao_mensal): o
-- publicado pelo IBGE quando existe. Nada é calculado aqui; o `filter` só põe IPCA e INPC lado a
-- lado. A evolução nos últimos 5 anos está em p4_brasil_ipca_x_inpc_5_anos.sql.
with ultimo_mes as (
    select max(mes_referencia) as mes
    from serie.fct_inflacao_mensal
    where indice = 'IPCA' and codigo_localidade = 1 and nivel_categoria = 'geral'
)
select
    l.nome_localidade as localidade,
    max(f.variacao_acum_12m_pct) filter (where f.indice = 'IPCA') as ipca_12m_pct,
    max(f.variacao_acum_12m_pct) filter (where f.indice = 'INPC') as inpc_12m_pct,
    to_char(u.mes, 'MM/YYYY') as ate_o_mes
from serie.fct_inflacao_mensal f
join ultimo_mes u on f.mes_referencia = u.mes
join serie.dim_localidade l on l.codigo_localidade = f.codigo_localidade
where f.nivel_categoria = 'geral'
group by l.codigo_localidade, l.nome_localidade, u.mes
order by l.codigo_localidade = 1 desc, ipca_12m_pct desc nulls last;
