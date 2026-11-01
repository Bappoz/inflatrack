-- Taxa Selic diária (PLAN_E3_E4.md, Seção 1.2 e 5.0.1).
-- Limpeza 1:1 da Bronze selic_taxa (série SGS 11 - BACEN).
-- Tipagem estrita e cálculo do fator diário multiplicador (1 + taxa_dia/100) para acumulação composta.

select
    data_referencia,
    cast(year(data_referencia) as smallint) as ano,
    cast(taxa_dia_pct as decimal(10, 6)) as taxa_dia_pct,
    cast(((1.0 + (taxa_dia_pct / 100.0)) ^ 252 - 1.0) * 100.0 as decimal(10, 4)) as taxa_anualizada_pct,
    cast(1.0 + (taxa_dia_pct / 100.0) as decimal(12, 8)) as fator_diario,
    _ingerido_em
from {{ source('bronze_selic', 'selic_taxa') }}
