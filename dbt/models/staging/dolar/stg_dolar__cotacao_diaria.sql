-- Cotação diária do Dólar Comercial PTAX (PLAN_E3_E4.md, Seção 1.2 e 5.0.1).
-- A Bronze guarda todos os boletins intradiários publicados no dia (Abertura, Intermediários
-- e Fechamento PTAX). Esta view seleciona o último boletim apurado do dia (fechamento oficial),
-- desempata por data_hora_cotacao e calcula o spread de fechamento.

with boletins as (
    select
        *,
        row_number() over (
            partition by data_referencia
            order by data_hora_cotacao desc, _ingerido_em desc
        ) as ordem_boletim,
        count(*) over (partition by data_referencia) as boletins_no_dia
    from {{ source('bronze_dolar', 'dolar_boletim') }}
)

select
    data_referencia,
    cast(year(data_referencia) as smallint) as ano,
    cast(cotacao_compra as decimal(10, 4)) as cotacao_compra,
    cast(cotacao_venda as decimal(10, 4)) as cotacao_venda,
    cast(cotacao_venda - cotacao_compra as decimal(10, 4)) as spread_fechamento,
    tipo_boletim,
    data_hora_cotacao,
    boletins_no_dia,
    _ingerido_em
from boletins
where ordem_boletim = 1
