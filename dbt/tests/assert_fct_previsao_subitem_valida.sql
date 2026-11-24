-- Erro típico negativo ou mês previsto que não é o seguinte ao último IPCA são defeitos do modelo.
select *
from {{ ref('fct_previsao_subitem') }}
where erro_tipico_pct < 0
   or mes_previsto <> mes_base + interval 1 month
