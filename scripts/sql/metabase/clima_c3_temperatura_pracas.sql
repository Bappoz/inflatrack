-- Painel do clima, C3: temperatura média mensal de quatro praças em climas diferentes, últimos 5
-- anos. A sazonalidade tem de aparecer (Porto Alegre oscila muito, Belém quase nada).
-- Lê serie.fct_clima_mensal.
select
    c.mes_referencia,
    max(c.temp_media) filter (where c.codigo_localidade = 3501) as sao_paulo,
    max(c.temp_media) filter (where c.codigo_localidade = 5300108) as brasilia,
    max(c.temp_media) filter (where c.codigo_localidade = 4301) as porto_alegre,
    max(c.temp_media) filter (where c.codigo_localidade = 1501) as belem
from serie.fct_clima_mensal as c
where c.mes_referencia >= (select max(mes_referencia) from serie.fct_clima_mensal)
    - interval '5 years'
group by c.mes_referencia
order by c.mes_referencia
