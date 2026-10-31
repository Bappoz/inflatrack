-- SCD tipo 2 da cesta. Uma versão nova abre quando a estrutura muda (troca de agregado/POF, que é
-- quando o IBGE muda os pesos de referência) ou quando o nome ou o pai da categoria mudam.
--
-- O peso mensal NÃO abre versão: o IBGE o atualiza todo mês com os preços relativos, e cada mês
-- seria uma versão. Ele é medida e mora em fct_inflacao_mensal; aqui ficam os pesos do início e do
-- fim de cada versão, que mostram o salto de cada revisão (decisão de 2026-10-31).
--
-- Vigência meio-aberta: vigencia_inicio entra, vigencia_fim não entra. Aberta = fim nulo.
-- A vigência vem dos meses com valor de fato, porque subitens entram e saem dentro de um agregado.

with mensal as (
    select * from {{ ref('int_ipca__mensal') }}
),

cobertura as (
    select
        indice,
        codigo_categoria,
        agregado_origem as agregado,
        min(mes_referencia) as primeiro_mes,
        max(mes_referencia) as ultimo_mes
    from mensal
    group by indice, codigo_categoria, agregado_origem
),

ultimo_publicado as (
    select indice, max(mes_referencia) as ultimo_mes
    from mensal
    group by indice
),

-- Só a versão 1 conhece o passado. Uma renomeação vale a partir do mês em que foi vista, limitada
-- ao último mês do agregado (a mesma regra de ipca.sincronizar_cesta).
versoes as (
    select
        c.indice,
        c.codigo_categoria,
        c.agregado,
        c.ultimo_mes,
        coalesce(m.versao, 1) as versao,
        coalesce(m.nome_categoria, 'Índice geral') as nome_categoria,
        m.codigo_pai,
        coalesce(m.nivel_categoria, 'geral') as nivel_categoria,
        case
            when coalesce(m.versao, 1) = 1 then c.primeiro_mes
            else least(
                greatest(
                    c.primeiro_mes,
                    cast(date_trunc('month', timezone('America/Sao_Paulo', m._ingerido_em)) as date)
                ),
                c.ultimo_mes
            )
        end as inicio
    from cobertura as c
    left join {{ ref('stg_ipca__metadados') }} as m
        on m.agregado = c.agregado
        and m.codigo_categoria = c.codigo_categoria
),

com_fim as (
    select
        *,
        coalesce(
            lead(inicio) over (partition by indice, codigo_categoria, agregado order by versao),
            cast(ultimo_mes + interval 1 month as date)
        ) as fim_exclusivo
    from versoes
),

-- Duas renomeações vistas no mesmo mês deixam a versão intermediária sem nenhum mês de vigência.
validas as (
    select * from com_fim where inicio < fim_exclusivo
)

select
    v.indice || '-' || v.codigo_categoria || '-' || v.agregado || '-' || v.versao as id_versao_cesta,
    v.indice,
    v.codigo_categoria,
    v.agregado,
    a.estrutura_cesta,
    cast(v.versao as smallint) as versao,
    v.nome_categoria,
    v.codigo_pai,
    v.nivel_categoria,
    v.inicio as vigencia_inicio,
    case when v.fim_exclusivo <= u.ultimo_mes then v.fim_exclusivo end as vigencia_fim,
    v.fim_exclusivo > u.ultimo_mes as versao_atual,
    inicio.peso_mensal_pct as peso_brasil_inicio_pct,
    fim.peso_mensal_pct as peso_brasil_fim_pct
from validas as v
inner join ultimo_publicado as u using (indice)
inner join {{ ref('seed_agregado_sidra') }} as a using (agregado)
left join mensal as inicio
    on inicio.indice = v.indice
    and inicio.codigo_categoria = v.codigo_categoria
    and inicio.codigo_localidade = 1
    and inicio.mes_referencia = v.inicio
left join mensal as fim
    on fim.indice = v.indice
    and fim.codigo_categoria = v.codigo_categoria
    and fim.codigo_localidade = 1
    and fim.mes_referencia = cast(v.fim_exclusivo - interval 1 month as date)
