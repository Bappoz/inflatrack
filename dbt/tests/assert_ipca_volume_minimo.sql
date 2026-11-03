-- Erro silencioso: a carga "passa" com a maior parte das linhas faltando. O mínimo é a contagem
-- medida em 2026-10-31 (1.662.314 linhas), com folga: a tabela só cresce, então cair abaixo de
-- 1,6 milhão quer dizer agregado que não entrou.
select count(*) as linhas
from {{ ref('fct_inflacao_mensal') }}
having count(*) < 1600000
