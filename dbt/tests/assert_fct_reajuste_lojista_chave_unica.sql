-- Grão declarado: uma linha por produto x mês.
select id_produto, mes_referencia, count(*) as linhas
from {{ ref('fct_reajuste_lojista') }}
group by all
having count(*) > 1
