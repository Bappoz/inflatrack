-- Metabase, pergunta 2 do projeto: "Em que meses do ano a inflação dos meus insumos costuma
-- pesar mais?" Uma linha por mês do ano: a variação mensal média do IPCA (Brasil) no índice
-- geral e nos grupos mais ligados ao comércio, de jul/2006 (início do agregado 2938) até o último
-- mês divulgado.
--
-- Lê só a vitrine `serie`. Os códigos de grupo (1 a 9) são estáveis entre os agregados do IPCA
-- (int_ipca__mensal). A média por mês do ano é o único cálculo e é provisória aqui: na E4 vai para
-- a camada semântica do dbt (gold.sem_*, Seção 5.2), e esta pergunta passa a só ler o resultado.
--
-- Falta: o efeito do clima. silver.int_clima__anomalia_mensal (chuva/temperatura com lags) ainda
-- não chega à Gold nem ao `serie`, e as medições diárias do INMET agora exigem token.
select
    lpad(extract(month from f.mes_referencia)::text, 2, '0') || ' '
        || (array['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov',
                  'dez'])[extract(month from f.mes_referencia)::int] as mes,
    round(avg(f.variacao_mensal_pct) filter (where f.nivel_categoria = 'geral'), 2)
        as indice_geral_pct,
    round(avg(f.variacao_mensal_pct) filter (where f.codigo_categoria = '1'), 2)
        as alimentacao_e_bebidas_pct,
    round(avg(f.variacao_mensal_pct) filter (where f.codigo_categoria = '2'), 2)
        as habitacao_pct,
    round(avg(f.variacao_mensal_pct) filter (where f.codigo_categoria = '4'), 2)
        as vestuario_pct,
    round(avg(f.variacao_mensal_pct) filter (where f.codigo_categoria = '5'), 2)
        as transportes_pct,
    count(distinct extract(year from f.mes_referencia)) as anos_na_media
from serie.fct_inflacao_mensal f
where f.indice = 'IPCA'
  and f.codigo_localidade = 1
  and f.nivel_categoria in ('geral', 'grupo')
  and f.mes_referencia >= date '2006-07-01'
group by 1
order by 1;
