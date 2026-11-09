-- Grão declarado de int_commodities__mensal: uma linha por symbol x mês.
select symbol, mes_referencia, count(*) as linhas
from {{ ref('int_commodities__mensal') }}
group by 1, 2
having count(*) > 1
