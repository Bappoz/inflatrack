-- Sujeiras típicas da fonte, no grão mensal:
-- * média mensal <= 0 (o WTI teve um pregão negativo em 20/04/2020, mas a média de abril
--   ficou positiva; uma média negativa indicaria preço com sinal ou unidade errados);
-- * mínimo acima do máximo;
-- * mais pregões no mês do que dias úteis possíveis (23), ou série mensal com mais de 1.
select symbol, mes_referencia, media, minimo, maximo, dias_observados, intervalo
from {{ ref('int_commodities__mensal') }}
where media <= 0
   or minimo > maximo
   or (intervalo = 'daily' and dias_observados > 23)
   or (intervalo = 'monthly' and dias_observados > 1)
