-- Uma linha por symbol x data, 1:1 com a Bronze. O marcador "." da Alpha Vantage já chega
-- como preco NULL; aqui ele vira observado = false, e a linha não some.
-- O preço negativo do WTI em 20/04/2020 (-36,98) é real e fica como está.

select
    symbol,
    intervalo,
    data_referencia,
    preco,
    preco is not null as observado,
    unidade,
    _ingerido_em
from {{ source('bronze_commodities', 'commodities_cotacao') }}
