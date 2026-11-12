-- Painel do clima, C2: no mês corrente, quantos dias vieram do INMET (oficial) e quantos do
-- Open-Meteo (provisório). O provisório só cobre os dias que o INMET ainda não publicou.
-- Lê serie.fct_clima_mensal.
with atual as (
    select max(mes_referencia) as mes from serie.fct_clima_mensal
)
select
    l.nome_localidade as praca,
    c.dias_com_registro - c.dias_provisorios as dias_oficiais_inmet,
    c.dias_provisorios as dias_provisorios_open_meteo
from serie.fct_clima_mensal as c
join atual as a on c.mes_referencia = a.mes
join serie.dim_localidade as l on l.codigo_localidade = c.codigo_localidade
order by praca
