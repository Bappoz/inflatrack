with mensal as (
    select * from {{ ref('stg_salario_minimo__mes') }}
)
select
    mes_referencia,
    ano,
    mes,
    salario_nominal,
    salario_necessario,
    cast(round(salario_necessario / nullif(salario_nominal, 0), 4) as decimal(12, 4))
        as multiplos_salario_necessario,
    cast(round(salario_nominal / nullif(lag(salario_nominal) over w, 0) * 100 - 100, 4)
        as decimal(12, 4)) as variacao_nominal_pct,
    cast(round(salario_necessario / nullif(lag(salario_necessario) over w, 0) * 100 - 100, 4)
        as decimal(12, 4)) as variacao_necessario_pct,
    cast(avg(salario_nominal) over (w rows between 2 preceding and current row) as decimal(14, 2))
        as media_movel_nominal_3m
from mensal
window w as (order by mes_referencia)