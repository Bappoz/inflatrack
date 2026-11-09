-- Metabase, pergunta 3 do projeto, outra metade: o salário mínimo acompanhou a inflação?
-- Uma linha por mês, de jan/2006 ao último mês do DIEESE: o salário mínimo nominal (o que a lei
-- fixou) e o mesmo valor corrigido pelo IPCA geral do Brasil para reais do último mês com
-- número-índice. A distância entre as duas linhas é a inflação do período; se a linha corrigida
-- sobe, o piso ganhou poder de compra.
--
-- Lê só a vitrine `serie`. O cálculo (correção pelo número-índice e ganho real em 12 meses) já vem
-- pronto da Gold (gold.fct_salario_minimo_mensal); aqui só se escolhe o recorte.
select
    mes_referencia,
    salario_nominal,
    salario_nominal_real as salario_corrigido_pelo_ipca,
    ganho_real_12m_pct
from serie.fct_salario_minimo_mensal
where mes_referencia >= date '2006-01-01'
order by mes_referencia;
