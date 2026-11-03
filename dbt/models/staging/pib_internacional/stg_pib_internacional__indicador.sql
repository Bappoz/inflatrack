-- Visão Silver Staging dos indicadores econômicos internacionais do Banco Mundial.
-- Grão: uma linha por (pais_iso3, indicador, ano) na versão mais recente coletada.

with versoes as (
    select
        *,
        row_number() over (
            partition by pais_iso3, indicador, ano
            order by _ingerido_em desc, _id_resposta desc
        ) as ordem_versao
    from {{ source('bronze_pib_internacional', 'pib_internacional_indicador') }}
)

select
    pais_iso3,
    pais_nome,
    pais_id,
    cast(ano as smallint) as ano,
    make_date(cast(ano as integer), 1, 1) as data_referencia,
    indicador as indicador_original,
    case
        when indicador = 'NY.GDP.MKTP.KD.ZG' then 'crescimento_pib_pct'
        when indicador = 'NY.GDP.MKTP.CD' then 'pib_nominal_usd'
        else indicador
    end as indicador_codigo,
    indicador_nome,
    cast(valor as decimal(24, 4)) as valor,
    unidade,
    obs_status,
    _ingerido_em
from versoes
where ordem_versao = 1
