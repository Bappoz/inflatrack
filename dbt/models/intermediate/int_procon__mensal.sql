with cesta as (
    select * from {{ ref('stg_procon__cesta_basica') }}
)
select
    data_pesquisa as mes_referencia,
    produto,
    unidade,
    praca,
    codigo_subitem_ipca,
    preco_medio,
    preco_minimo,
    preco_maximo,
    cast(lag(preco_medio) over w as decimal(14, 2)) as preco_medio_anterior,
    cast(round(
        (preco_medio / nullif(lag(preco_medio) over w, 0) - 1.0) * 100.0,
        4
    ) as decimal(12, 4)) as variacao_mensal_preco_pct
from cesta
window w as (
    partition by produto, praca
    order by data_pesquisa
)
