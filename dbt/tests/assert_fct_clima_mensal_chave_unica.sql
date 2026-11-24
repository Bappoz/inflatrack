-- Grão declarado: uma linha por praça do IPCA x mês.
select codigo_localidade, mes_referencia, count(*) as linhas
from {{ ref('fct_clima_mensal') }}
group by all
having count(*) > 1
