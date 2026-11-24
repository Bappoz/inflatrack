-- Grão declarado: uma linha por polo (estação) x mês.
select estacao_id, mes_referencia, count(*) as linhas
from {{ ref('fct_clima_polo_mensal') }}
group by all
having count(*) > 1
