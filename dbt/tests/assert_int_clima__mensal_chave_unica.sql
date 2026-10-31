select estacao_id, mes_referencia, count(*) as linhas
from {{ ref('int_clima__anomalia_mensal') }}
group by estacao_id, mes_referencia
having count(*) > 1