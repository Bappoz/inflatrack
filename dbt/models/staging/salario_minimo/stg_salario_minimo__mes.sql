select
    cast(data_referencia as date) as mes_referencia,
    cast(ano as smallint) as ano,
    cast(mes as tinyint) as mes,
    cast(salario_nominal as decimal(14, 2)) as salario_nominal,
    cast(salario_necessario as decimal(14, 2)) as salario_necessario,
    _ingerido_em
from {{ source('bronze_salario_minimo', 'salario_minimo_mes') }}
qualify row_number() over (partition by ano_mes order by _ingerido_em desc) = 1