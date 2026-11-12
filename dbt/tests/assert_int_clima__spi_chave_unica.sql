-- Grão declarado: uma linha por estação x mês, e SPI dentro do limite de ±3.
select estacao_id, mes_referencia, count(*) as linhas
from {{ ref('int_clima__spi_mensal') }}
group by all
having count(*) > 1 or max(abs(spi_3)) > 3.0001
