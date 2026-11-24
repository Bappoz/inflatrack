-- Salário mínimo (DIEESE) frente à inflação, um mês por linha: o que o piso comprou ao longo do
-- tempo (PLAN_E3_E4.md, Seção 5.2, pergunta 3). A Silver do salário mínimo e o IPCA da Gold se
-- encontram pela dim_calendario (Seção 6.1).
--
-- ganho_real_12m_pct = (1 + reajuste nominal em 12 meses) / (1 + IPCA em 12 meses) - 1: positivo
-- quando o salário mínimo subiu acima da inflação.
-- salario_nominal_real = salário de cada mês em reais do mes_base_real (último mês com
-- número-índice do IPCA geral do Brasil), isto é, o valor corrigido pelo IPCA: a série fica
-- comparável ao longo do tempo.

with sm as (
    select * from {{ ref('int_salario_minimo__mensal') }}
),

ipca_brasil as (
    select mes_referencia, numero_indice, variacao_acum_12m_pct as ipca_12m
    from {{ ref('fct_inflacao_mensal') }}
    where indice = 'IPCA' and nivel_categoria = 'geral' and codigo_localidade = 1
),

base as (
    select mes_referencia as mes_base_real, numero_indice as indice_base
    from ipca_brasil
    where numero_indice is not null
    order by mes_referencia desc
    limit 1
),

meses as (
    select c.mes_referencia
    from {{ ref('dim_calendario') }} as c
    where c.mes_referencia between (select min(mes_referencia) from sm)
        and (select max(mes_referencia) from sm)
),

combinado as (
    select
        m.mes_referencia,
        s.salario_nominal,
        s.salario_necessario,
        s.multiplos_salario_necessario,
        s.variacao_nominal_pct,
        s.variacao_necessario_pct,
        s.media_movel_nominal_3m,
        lag(s.salario_nominal, 12) over (order by m.mes_referencia) as nominal_12m_atras,
        i.ipca_12m,
        i.numero_indice
    from meses as m
    left join sm as s using (mes_referencia)
    left join ipca_brasil as i using (mes_referencia)
)

select
    c.mes_referencia,
    c.salario_nominal,
    c.salario_necessario,
    c.multiplos_salario_necessario,
    c.variacao_nominal_pct,
    c.variacao_necessario_pct,
    c.media_movel_nominal_3m,
    cast(round((c.salario_nominal / nullif(c.nominal_12m_atras, 0) - 1) * 100, 4)
        as decimal(12, 4)) as variacao_nominal_12m_pct,
    cast(c.ipca_12m as decimal(12, 4)) as ipca_12m_pct,
    cast(round(
        ((c.salario_nominal / nullif(c.nominal_12m_atras, 0))
            / nullif(1 + c.ipca_12m / 100, 0) - 1) * 100, 4
    ) as decimal(12, 4)) as ganho_real_12m_pct,
    b.mes_base_real,
    cast(round(c.salario_nominal * b.indice_base / nullif(c.numero_indice, 0), 2)
        as decimal(14, 2)) as salario_nominal_real,
    cast(round(c.salario_necessario * b.indice_base / nullif(c.numero_indice, 0), 2)
        as decimal(14, 2)) as salario_necessario_real
from combinado as c
cross join base as b
