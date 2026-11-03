select
    estacao_id,
    nome,
    estado,
    tipo,
    cast(latitude as decimal(9, 6)) as latitude,
    cast(longitude as decimal(9, 6)) as longitude,
    cast(altitude_m as decimal(8, 2)) as altitude_m,
    situacao,
    data_inicio_operacao,
    data_fim_operacao,
    _ingerido_em
from {{ source('bronze_clima', 'clima_estacao') }}
qualify row_number() over (partition by estacao_id order by _ingerido_em desc) = 1