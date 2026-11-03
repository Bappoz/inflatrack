-- Pergunta 1/4 do lojista: a série de 12 meses de uma categoria na praça dele, com a versão da
-- cesta da época. Medida por scripts/explain_serie.py sem e com fct_inflacao_mensal_consulta_idx.
-- Arroz (1101002) em Brasília (5300108), do mês mais recente para trás.
select
    f.mes_referencia,
    c.nome_categoria,
    f.variacao_mensal_pct,
    f.variacao_acum_12m_pct
from serie.fct_inflacao_mensal as f
inner join serie.dim_cesta_ipca_scd2 as c on c.id_versao_cesta = f.id_versao_cesta
where f.codigo_categoria = '1101002'
    and f.codigo_localidade = 5300108
    and f.indice = 'IPCA'
order by f.mes_referencia desc
limit 12
