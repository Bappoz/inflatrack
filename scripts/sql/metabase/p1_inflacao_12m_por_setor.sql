-- Metabase, pergunta 1 do projeto: "Qual foi a inflação acumulada do meu setor nos últimos
-- 12 meses?" Uma linha por grupo do IPCA (o setor do lojista), Brasil, último mês divulgado.
--
-- PROVISÓRIO (E3): lê o IPCA oficial que já está no Postgres (public.observacao), porque a
-- gold.fct_inflacao_mensal (Lucas) ainda não existe. Quando ela existir, esta pergunta passa a
-- ler a Gold. O acumulado vem pronto do IBGE (agregado 7060, variável 2265); nada é calculado
-- aqui. A observacao só acrescenta: se o IBGE revisou um valor, vale a linha mais recente.
--
-- Conferência (2026-10-30, dado até 09/2026): o produto das 12 variações mensais (variável 63)
-- dá o mesmo acumulado para o Índice geral (4,58%) e o Vestuário (3,34%); em Alimentação e
-- bebidas, 4,64% contra 4,66%, diferença do arredondamento das mensais a 2 casas.
with ultimo_mes as (
    select max(mes_referencia) as mes
    from observacao
    where id_fonte = 7060 and codigo_variavel = 2265 and codigo_localidade = 1
),
valores as (
    select distinct on (o.codigo_classificacao)
        o.codigo_classificacao, o.mes_referencia, o.valor
    from observacao o, ultimo_mes u
    where o.id_fonte = 7060
      and o.codigo_variavel = 2265
      and o.codigo_localidade = 1
      and o.mes_referencia = u.mes
    order by o.codigo_classificacao, o.ingerido_em desc
)
select
    v.nome as setor,
    c.nivel,
    round(x.valor, 2) as inflacao_12m_pct,
    to_char(x.mes_referencia, 'MM/YYYY') as ate_o_mes
from valores x
join classificacao c on c.codigo = x.codigo_classificacao
join classificacao_versao v
    on v.codigo = x.codigo_classificacao and v.id_fonte = 7060 and v.vigencia_fim is null
where c.nivel in ('geral', 'grupo')
order by c.nivel = 'geral' desc, x.valor desc;
