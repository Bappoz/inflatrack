-- Uma linha por setor x trimestre, na versão mais recente que o IBGE publicou.
-- A Bronze guarda todas as versões (cada revisão é linha nova); aqui fica só a última
-- coletada, desempatando por _ingerido_em (decisão de 2026-10-29, sem ADR).

with versoes as (
    select
        *,
        row_number() over (
            partition by codigo_setor, data_referencia
            order by _ingerido_em desc, _id_resposta desc
        ) as ordem_versao,
        count(*) over (partition by codigo_setor, data_referencia) as versoes_coletadas
    from {{ source('bronze_pib', 'pib_valor') }}
)

select
    data_referencia as trimestre_inicio,
    cast(year(data_referencia) as smallint) as ano,
    cast(quarter(data_referencia) as tinyint) as trimestre,
    codigo_setor,
    nome_setor,
    cast(valor as decimal(20, 4)) as valor_milhoes_brl,
    valor_bruto,
    versoes_coletadas,
    _ingerido_em
from versoes
where ordem_versao = 1
