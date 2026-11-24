-- RONI por mês central da temporada (DJF -> jan, ..., NDJ -> dez), última revisão do NOAA.
select
    cast(mes_referencia as date) as mes_referencia,
    temporada,
    cast(roni as decimal(5, 2)) as roni,
    _ingerido_em
from {{ source('bronze_enso', 'enso_roni') }}
qualify row_number() over (
    partition by mes_referencia order by _ingerido_em desc, id_leitura desc
) = 1
