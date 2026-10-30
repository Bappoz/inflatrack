-- O bloco MODELO de int_pib__mensal nunca pode usar um trimestre que, no mês da linha,
-- ainda não tinha sido divulgado (trimestre_inicio + 5 meses > mes_referencia).
-- Também falha se o "último divulgado" for mais novo que o trimestre do próprio mês.
-- Toda linha devolvida é uma violação.

select
    mes_referencia,
    codigo_setor,
    trimestre_ultimo_divulgado
from {{ ref('int_pib__mensal') }}
where cast(trimestre_ultimo_divulgado + interval 5 month as date) > mes_referencia
   or trimestre_ultimo_divulgado >= trimestre_referencia
