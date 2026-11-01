-- Grão declarado de int_macroeconomia__mensal: uma linha por mês de referência.
select mes_referencia, count(*) as linhas
from {{ ref('int_macroeconomia__mensal') }}
group by 1
having count(*) > 1
