-- Uma estação é de praça do IPCA OU de polo agrícola: nos dois seeds, a Gold a contaria duas vezes
-- com papéis diferentes e a coleta não saberia a qual pertence.
select p.estacao_id
from {{ ref('seed_estacao_polo_agricola') }} as p
inner join {{ ref('seed_de_para_estacao_localidade') }} as d using (estacao_id)
