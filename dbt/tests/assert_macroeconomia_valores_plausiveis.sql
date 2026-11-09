-- Validação de consistência e plausibilidade física/econômica no grão mensal:
-- * Cotação do dólar (média e fechamento) dentro de faixa plausível (R$ 1.00 a R$ 20.00);
-- * Mínimo de cotação mensal não pode ser maior que o máximo;
-- * Spread médio de fechamento do dólar não pode ser negativo;
-- * Taxa Selic anualizada de fim de mês entre 0% e 100% a.a.;
-- * Selic acumulada no mês positiva (ou nula);
-- * Dias úteis observados de câmbio ou Selic no mês entre 1 e 23 dias úteis.
select
    mes_referencia,
    dolar_media,
    dolar_minimo,
    dolar_maximo,
    dolar_fechamento,
    spread_medio,
    dias_uteis_dolar,
    selic_anualizada_fim_mes_pct,
    selic_acumulada_mes_pct,
    dias_uteis_selic
from {{ ref('int_macroeconomia__mensal') }}
where dolar_media <= 1.0 or dolar_media > 20.0
   or dolar_fechamento <= 1.0 or dolar_fechamento > 20.0
   or dolar_minimo > dolar_maximo
   or spread_medio < 0
   or dias_uteis_dolar < 1 or dias_uteis_dolar > 23
   or selic_anualizada_fim_mes_pct < 0 or selic_anualizada_fim_mes_pct > 100.0
   or selic_acumulada_mes_pct < 0
   or dias_uteis_selic < 1 or dias_uteis_selic > 23
