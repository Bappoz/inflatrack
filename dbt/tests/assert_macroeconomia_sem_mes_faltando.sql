-- "Mês que some": entre o primeiro e o último mês da série macroeconômica não pode faltar mês.
select count(*) as linhas, min(mes_referencia) as primeiro, max(mes_referencia) as ultimo
from {{ ref('int_macroeconomia__mensal') }}
having count(*) <> date_diff('month', min(mes_referencia), max(mes_referencia)) + 1
