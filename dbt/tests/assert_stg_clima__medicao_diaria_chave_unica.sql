-- Grão declarado: uma linha por estação x dia. Pega dia com dado oficial E provisório ao mesmo
-- tempo (o provisório só pode existir depois do último dia oficial).
select estacao_id, data_referencia, count(*) as linhas
from {{ ref('stg_clima__medicao_diaria') }}
group by all
having count(*) > 1
