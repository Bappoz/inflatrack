-- Calendário mensal mestre: ponto de encontro das Silvers na Gold (PLAN_E3_E4.md, Seção 6.1).
-- Vai de jan/1979 (a série 1737 do IPCA começa em dez/1979) até dez do ano seguinte ao
-- do build, para não precisar de manutenção na virada do ano.

with meses as (
    select cast(mes as date) as mes_referencia
    from generate_series(
        date '1979-01-01',
        cast(date_trunc('year', current_date) + interval 2 year - interval 1 month as date),
        interval 1 month
    ) as t(mes)
)

select
    mes_referencia,
    cast(year(mes_referencia) as smallint) as ano,
    cast(month(mes_referencia) as tinyint) as mes,
    cast(quarter(mes_referencia) as tinyint) as trimestre,
    cast(case when month(mes_referencia) <= 6 then 1 else 2 end as tinyint) as semestre,
    strftime(mes_referencia, '%Y-%m') as ano_mes,
    cast(date_trunc('quarter', mes_referencia) as date) as trimestre_inicio,
    cast(last_day(mes_referencia) as date) as ultimo_dia
from meses
