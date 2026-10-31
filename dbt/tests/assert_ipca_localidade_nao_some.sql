-- Uma localidade não some entre dois meses. O IPCA começou em 2006 com 12 localidades (Brasil + 11
-- praças) e o IBGE acrescentou as outras depois, sem nunca tirar nenhuma: em cada uma, os meses
-- são contínuos do primeiro até o último publicado.
with geral as (
    select
        indice,
        codigo_localidade,
        mes_referencia,
        lag(mes_referencia) over (
            partition by indice, codigo_localidade order by mes_referencia
        ) as anterior
    from {{ ref('fct_inflacao_mensal') }}
    where codigo_categoria = '7169' and agregado_origem <> 1737
),

ultimos as (
    select indice, codigo_localidade, max(mes_referencia) as ultimo
    from geral
    group by indice, codigo_localidade
),

ultimo_do_indice as (
    select indice, max(ultimo) as ultimo from ultimos group by indice
)

select indice, codigo_localidade, mes_referencia as mes, 'buraco na série' as problema
from geral
where anterior is not null and mes_referencia <> cast(anterior + interval 1 month as date)

union all

select u.indice, u.codigo_localidade, u.ultimo, 'parou antes do fim'
from ultimos as u
inner join ultimo_do_indice as t using (indice)
where u.ultimo < t.ultimo
