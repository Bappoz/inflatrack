-- Plausibilidade física no grão diário e no mensal (PLAN_E3_E4.md, Seção 6: zero é medida,
-- -9999 é ausência). A Bronze já anula leituras horárias fora das faixas físicas; isto pega o
-- que escapar na agregação.
--   * mínima do dia não passa da máxima;
--   * chuva nunca negativa; umidade entre 0 e 100%;
--   * cobertura mensal entre 0 e 1 e nunca mais dias medidos que dias no mês.
select 'diario' as grao, estacao_id as chave, data_referencia as referencia
from {{ ref('stg_clima__medicao_diaria') }}
where temp_min > temp_max
   or precipitacao_total_mm < 0
   or umidade_relativa_media_pct not between 0 and 100

union all

select 'mensal', cast(codigo_localidade as varchar), mes_referencia
from {{ ref('fct_clima_mensal') }}
where cobertura_dias not between 0 and 1
   or dias_com_registro > dias_no_mes
   or temp_min_absoluta > temp_max_absoluta
   or precipitacao_total_mm < 0
