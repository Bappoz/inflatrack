-- Erro silencioso típico do PIB: trimestre com setor faltando, ou trimestre que some no meio
-- da série. Todo trimestre entre o primeiro e o último precisa ter os 23 setores do catálogo.
with esperado as (
    select cast(t as date) as trimestre_inicio
    from (select min(trimestre_inicio) as ini, max(trimestre_inicio) as fim from {{ ref('stg_pib__valor') }}),
        generate_series(ini, fim, interval 3 month) as g(t)
),

contagem as (
    select trimestre_inicio, count(*) filter (where valor_milhoes_brl is not null) as setores
    from {{ ref('stg_pib__valor') }}
    group by 1
)

select e.trimestre_inicio, coalesce(c.setores, 0) as setores
from esperado as e
left join contagem as c using (trimestre_inicio)
where coalesce(c.setores, 0) <> (select count(*) from {{ ref('seed_pib_setor_catalogo') }})
