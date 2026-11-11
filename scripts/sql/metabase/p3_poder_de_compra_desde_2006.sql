-- Metabase, pergunta 3 do projeto: "Quanto a inflação comeu do poder de compra desde 2006?"
-- Uma linha por mês, de jan/2006 ao último mês divulgado: quanto R$ 100 de jan/2006 compram em
-- cada mês e a inflação acumulada no período (IPCA, índice geral, Brasil).
--
-- Lê só a vitrine `serie`. O número-índice (série 1737, base dez/1993 = 100) vem pronto da Gold
-- (gold.fct_inflacao_mensal.numero_indice, só no índice geral do Brasil). A razão entre dois
-- números-índice é o único cálculo e é provisória aqui: na E4 a "perda de poder de compra desde
-- 2006" vira métrica da camada semântica do dbt (gold.sem_*, Seção 5.2).
--
-- O outro lado da pergunta, o salário mínimo do DIEESE, está em p3_salario_minimo_real.sql.
with base as (
    select numero_indice
    from serie.fct_inflacao_mensal
    where indice = 'IPCA'
      and codigo_localidade = 1
      and nivel_categoria = 'geral'
      and mes_referencia = date '2006-01-01'
)
select
    f.mes_referencia,
    round(100 * b.numero_indice / f.numero_indice, 2) as poder_de_compra_de_100_reais,
    round((f.numero_indice / b.numero_indice - 1) * 100, 2) as inflacao_acumulada_desde_2006_pct
from serie.fct_inflacao_mensal f
cross join base b
where f.indice = 'IPCA'
  and f.codigo_localidade = 1
  and f.nivel_categoria = 'geral'
  and f.numero_indice is not null
  and f.mes_referencia >= date '2006-01-01'
order by f.mes_referencia;
