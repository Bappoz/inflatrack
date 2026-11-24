-- Painel do clima, C1: o dado está chegando? Uma linha por praça do IPCA, as piores primeiro.
-- Último mês com dado, último mês que o INMET já publicou inteiro, dias do mês corrente (e quantos
-- são provisórios, do Open-Meteo) e cobertura dos últimos 12 meses. Lê serie.fct_clima_mensal.
with atual as (
    select max(mes_referencia) as mes from serie.fct_clima_mensal
)
select
    l.nome_localidade as praca,
    max(c.mes_referencia) filter (where c.dias_com_registro > 0) as ultimo_mes_com_dado,
    max(c.mes_referencia) filter (where c.mes_fechado) as ultimo_mes_fechado,
    max(c.dias_com_registro) filter (where c.mes_referencia = a.mes) as dias_no_mes_atual,
    max(c.dias_provisorios) filter (where c.mes_referencia = a.mes) as dias_provisorios_no_mes_atual,
    round(avg(c.cobertura_dias) filter (
        where c.mes_referencia > a.mes - interval '12 months'
    ), 2) as cobertura_12_meses
from serie.fct_clima_mensal as c
cross join atual as a
join serie.dim_localidade as l on l.codigo_localidade = c.codigo_localidade
group by l.nome_localidade
order by cobertura_12_meses nulls first, praca
