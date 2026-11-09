-- Grão declarado de int_pib__mensal: uma linha por setor x mês.
select codigo_setor, mes_referencia, count(*) as linhas
from {{ ref('int_pib__mensal') }}
group by 1, 2
having count(*) > 1
