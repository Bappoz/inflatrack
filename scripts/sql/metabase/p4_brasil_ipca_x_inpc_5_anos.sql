-- Metabase, pergunta 4 do projeto (evolução): IPCA x INPC acumulados em 12 meses, índice geral,
-- Brasil, mês a mês nos últimos 5 anos (60 meses até o último divulgado).
--
-- Lê só a vitrine `serie`. Os acumulados vêm prontos da Gold (gold.fct_inflacao_mensal). Nada é
-- calculado aqui; o `filter` só põe as duas séries lado a lado. O recorte por praça está em
-- p4_brasil_x_regiao.sql.
with ultimo_mes as (
    select max(mes_referencia) as mes
    from serie.fct_inflacao_mensal
    where indice = 'IPCA' and codigo_localidade = 1 and nivel_categoria = 'geral'
)
select
    f.mes_referencia,
    max(f.variacao_acum_12m_pct) filter (where f.indice = 'IPCA') as ipca_12m_pct,
    max(f.variacao_acum_12m_pct) filter (where f.indice = 'INPC') as inpc_12m_pct
from serie.fct_inflacao_mensal f
cross join ultimo_mes u
where f.codigo_localidade = 1
  and f.nivel_categoria = 'geral'
  and f.mes_referencia > u.mes - interval '60 months'
group by f.mes_referencia
order by f.mes_referencia;
