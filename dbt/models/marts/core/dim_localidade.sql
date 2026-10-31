select
    cast(codigo_ibge as varchar) as codigo_localidade,
    nome,
    tipo,
    uf
from {{ ref('seed_localidade_ibge') }}