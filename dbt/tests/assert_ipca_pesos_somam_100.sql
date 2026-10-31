-- Os grupos da cesta somam 100% em toda localidade e todo mês. A folga é do arredondamento do
-- IBGE; passar dela quer dizer categoria faltando ou repetida na união dos agregados.
select indice, codigo_localidade, mes_referencia, sum(peso_mensal_pct) as soma
from {{ ref('fct_inflacao_mensal') }}
where nivel_categoria = 'grupo'
group by all
having abs(sum(peso_mensal_pct) - 100) > 0.5
