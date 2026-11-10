select
    cast(data_pesquisa as date) as data_pesquisa,
    cast(produto as varchar) as produto,
    cast(unidade as varchar) as unidade,
    cast(preco_medio as decimal(14, 2)) as preco_medio,
    cast(preco_minimo as decimal(14, 2)) as preco_minimo,
    cast(preco_maximo as decimal(14, 2)) as preco_maximo,
    cast(praca as varchar) as praca,
    cast(codigo_subitem_ipca as varchar) as codigo_subitem_ipca,
    _ingerido_em
from {{ source('bronze_procon', 'procon_cesta_basica') }}
qualify row_number() over (
    partition by data_pesquisa, produto, praca
    order by _ingerido_em desc
) = 1
