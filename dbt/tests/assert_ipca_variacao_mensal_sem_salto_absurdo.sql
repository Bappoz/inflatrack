-- Sujeira típica de carga, com limites medidos em 2026-10-31 sobre jul/2006 a set/2026:
-- índice geral entre -2,12% e 2,54% (limite 5%); subitem chega a 358,36% de verdade (5102015 em
-- Porto Alegre, jun/2024), então o limite é 500%. Queda de 100% ou mais é impossível em preço.
select indice, codigo_categoria, codigo_localidade, mes_referencia, variacao_mensal_pct
from {{ ref('fct_inflacao_mensal') }}
where mes_referencia >= date '2006-07-01'
    and (
        variacao_mensal_pct <= -100
        or abs(variacao_mensal_pct) > 500
        or (codigo_categoria = '7169' and abs(variacao_mensal_pct) > 5)
    )
