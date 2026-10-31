-- O acumulado que a Silver calcula para 2006-2011 precisa ser confiável. A prova é rodar a mesma
-- conta onde o IBGE publica o número: no índice geral e nos grupos, a diferença máxima medida em
-- 2026-10-31 foi de 0,0326 ponto percentual, efeito do arredondamento das variações mensais.
select indice, codigo_categoria, codigo_localidade, mes_referencia,
    variacao_acum_12m_pct, variacao_acum_12m_calculada_pct
from {{ ref('int_ipca__mensal') }}
where origem_acum_12m = 'publicado'
    and (length(codigo_categoria) = 1 or codigo_categoria = '7169')
    and codigo_localidade = 1
    and mes_referencia >= date '2013-01-01'
    and abs(variacao_acum_12m_pct - variacao_acum_12m_calculada_pct) > 0.05
