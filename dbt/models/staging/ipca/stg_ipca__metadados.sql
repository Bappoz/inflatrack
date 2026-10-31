-- Uma linha por versão de categoria em cada agregado. A Bronze só ganha linha quando o nome ou o
-- pai mudam, então a ordem de chegada (_ingerido_em) é a ordem das versões.

select
    cast(agregado as smallint) as agregado,
    id_categoria,
    codigo as codigo_categoria,
    trim(nome) as nome_categoria,
    codigo_pai,
    nivel as nivel_categoria,
    cast(row_number() over versoes as smallint) as versao,
    row_number() over versoes = count(*) over (partition by agregado, id_categoria) as versao_atual,
    _ingerido_em
from {{ source('bronze_ipca', 'ipca_metadados') }}
window versoes as (partition by agregado, id_categoria order by _ingerido_em, nome)
