-- Grão declarado: uma linha por índice x categoria x localidade x mês.
select indice, codigo_categoria, codigo_localidade, mes_referencia, count(*) as linhas
from {{ ref('fct_inflacao_mensal') }}
group by all
having count(*) > 1
