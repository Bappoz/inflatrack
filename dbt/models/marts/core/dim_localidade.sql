-- As 17 localidades medidas pelo IPCA. Só elas são válidas como praça do lojista.

select
    codigo_localidade,
    nome_localidade,
    tipo_localidade,
    uf
from {{ ref('seed_localidade_ibge') }}
