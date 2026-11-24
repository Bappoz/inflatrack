-- Painel do clima, C5: El Niño e La Niña desde 2006 (RONI do NOAA). Intensidade no formato do
-- Banco Central: quanto o índice passou do limiar de 0,5 °C (La Niña aparece negativa).
-- Lê serie.fct_enso_mensal.
select
    e.mes_referencia,
    e.roni,
    e.intensidade_el_nino,
    -e.intensidade_la_nina as intensidade_la_nina
from serie.fct_enso_mensal as e
where e.mes_referencia >= date '2006-01-01'
order by e.mes_referencia
