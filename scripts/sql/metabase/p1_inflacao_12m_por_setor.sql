-- Metabase, pergunta 1 do projeto: "Qual foi a inflação acumulada do meu setor nos últimos
-- 12 meses?" Uma linha por grupo do IPCA (o setor do lojista), Brasil, último mês divulgado.
--
-- Lê só a vitrine `serie` (cópia da Gold feita pelo ativo serie_postgres). O acumulado de 12
-- meses vem pronto da Gold (gold.fct_inflacao_mensal): o publicado pelo IBGE quando existe,
-- calculado no dbt quando não (coluna origem_acum_12m). Nada é calculado aqui.
--
-- Conferência (2026-11-03, dado até 09/2026): Índice geral 4,58%, Alimentação e bebidas 4,66%
-- e Vestuário 3,34%, os mesmos números da versão provisória que lia public.observacao.
with ultimo_mes as (
    select max(mes_referencia) as mes
    from serie.fct_inflacao_mensal
    where indice = 'IPCA' and codigo_localidade = 1 and nivel_categoria = 'geral'
)
select
    c.nome_categoria as setor,
    f.nivel_categoria as nivel,
    round(f.variacao_acum_12m_pct, 2) as inflacao_12m_pct,
    to_char(f.mes_referencia, 'MM/YYYY') as ate_o_mes
from serie.fct_inflacao_mensal f
join ultimo_mes u on f.mes_referencia = u.mes
join serie.dim_cesta_ipca_scd2 c on c.id_versao_cesta = f.id_versao_cesta
where f.indice = 'IPCA'
  and f.codigo_localidade = 1
  and f.nivel_categoria in ('geral', 'grupo')
order by f.nivel_categoria = 'geral' desc, f.variacao_acum_12m_pct desc;
