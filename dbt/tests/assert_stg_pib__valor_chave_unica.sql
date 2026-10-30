-- Grão declarado de stg_pib__valor: uma linha por setor x trimestre (só a versão mais recente).
select codigo_setor, trimestre_inicio, count(*) as linhas
from {{ ref('stg_pib__valor') }}
group by 1, 2
having count(*) > 1
