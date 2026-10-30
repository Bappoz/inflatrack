-- "Mês que some": entre o primeiro e o último mês de cada commodity não pode faltar linha.
select symbol, count(*) as linhas, min(mes_referencia) as primeiro, max(mes_referencia) as ultimo
from {{ ref('int_commodities__mensal') }}
group by 1
having count(*) <> date_diff('month', min(mes_referencia), max(mes_referencia)) + 1
