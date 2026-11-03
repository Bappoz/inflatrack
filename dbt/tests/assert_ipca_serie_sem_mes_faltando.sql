-- O índice geral do Brasil é contínuo desde dez/1979: mês que some aqui é carga incompleta.
with meses as (
    select mes_referencia,
        lag(mes_referencia) over (order by mes_referencia) as anterior
    from {{ ref('fct_inflacao_mensal') }}
    where indice = 'IPCA' and codigo_categoria = '7169' and codigo_localidade = 1
)

select mes_referencia, anterior
from meses
where anterior is not null
    and mes_referencia <> cast(anterior + interval 1 month as date)
