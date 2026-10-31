-- Isolamento (PLAN_E3_E4.md, Seção 2.2): a fato oficial não tem coluna nenhuma do lojista.
select column_name
from information_schema.columns
where table_schema = 'gold'
    and table_name = 'fct_inflacao_mensal'
    and (
        column_name like '%lojista%'
        or column_name like '%produto%'
        or column_name like '%estabelecimento%'
    )
