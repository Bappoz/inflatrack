-- Fato do PIB Internacional (Star Schema / Camada Gold):
-- Grão: uma linha por (ano, pais_iso3).
-- Pivoteia crescimento_pib_pct e pib_nominal_usd lado a lado por país parceiro.

with base as (
    select
        ano,
        data_referencia,
        pais_iso3,
        pais_nome,
        indicador_codigo,
        valor
    from {{ ref('stg_pib_internacional__indicador') }}
)

select
    ano,
    data_referencia,
    pais_iso3,
    pais_nome,
    max(case when indicador_codigo = 'crescimento_pib_pct' then valor end) as crescimento_pib_pct,
    max(case when indicador_codigo = 'pib_nominal_usd' then valor end) as pib_nominal_usd
from base
group by
    ano,
    data_referencia,
    pais_iso3,
    pais_nome
