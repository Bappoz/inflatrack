select
    id_medicao,
    estacao_id,
    cast(data_referencia as date) as data_referencia,
    cast(temp_min as decimal(8, 3)) as temp_min,
    cast(temp_max as decimal(8, 3)) as temp_max,
    cast(temp_media as decimal(8, 3)) as temp_media,
    cast(precipitacao_total_mm as decimal(10, 3)) as precipitacao_total_mm,
    cast(umidade_relativa_media_pct as decimal(8, 3)) as umidade_relativa_media_pct,
    cast(umidade_relativa_min_pct as decimal(8, 3)) as umidade_relativa_min_pct,
    observado,
    _ingerido_em
from {{ source('bronze_clima', 'clima_medicao') }}
qualify row_number() over (
    partition by estacao_id, data_referencia
    order by _ingerido_em desc, id_medicao desc
) = 1