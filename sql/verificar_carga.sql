-- Confere o volume carregado contra o que a API do SIDRA publica.
-- Números medidos em 2026-09-08 (1 mês amostrado por fonte x nº de meses):
--   2938  ~798.138    1419  ~2.187.264    7060  ~1.707.980
-- Divergência acima de 1% quer dizer mês faltando ou filtro comendo dado.
select f.id                                            as fonte,
       f.indice,
       count(o.id)                                     as linhas,
       min(o.mes_referencia)                           as primeiro_mes,
       max(o.mes_referencia)                           as ultimo_mes,
       count(distinct o.mes_referencia)                as meses,
       count(distinct o.codigo_localidade)             as localidades,
       count(distinct o.codigo_classificacao)          as categorias
from fonte_agregado f
left join observacao o on o.id_fonte = f.id
group by f.id, f.indice
order by f.id;

-- Nenhum mês pode faltar no meio da série de uma fonte viva.
select id_fonte,
       count(distinct mes_referencia)                                        as meses_carregados,
       (extract(year from age(max(mes_referencia), min(mes_referencia))) * 12
        + extract(month from age(max(mes_referencia), min(mes_referencia))) + 1)::int as meses_esperados
from observacao
group by id_fonte
having count(distinct mes_referencia) <> (
        extract(year from age(max(mes_referencia), min(mes_referencia))) * 12
        + extract(month from age(max(mes_referencia), min(mes_referencia))) + 1)::int;
