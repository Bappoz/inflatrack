-- SCD tipo 2 do produto do lojista: uma versão por período em que preço, custo, nome e subitem
-- ficaram iguais. Vigência meio-aberta: vigencia_inicio entra, vigencia_fim não entra. A versão é
-- fechada na exclusão do produto, e a linha do produto excluído não é apagada: o histórico fica.
--
-- Derivada do log do CDC, e não de `dbt snapshot`: o snapshot só veria o estado na hora em que
-- roda, perderia as mudanças entre duas execuções e não conseguiria encaixar um evento atrasado.

with eventos as (
    select * from {{ ref('int_transacional__precos') }}
),

exclusoes as (
    select id_produto, min(efetivo_em) as excluido_em
    from eventos
    where excluido
    group by id_produto
),

ativos as (
    select
        *,
        lag(preco_centavos) over produto as preco_anterior,
        lag(custo_centavos) over produto as custo_anterior,
        lag(nome_produto) over produto as nome_anterior,
        lag(codigo_subitem_ipca) over produto as subitem_anterior,
        row_number() over produto as ordem
    from eventos
    where not excluido
    window produto as (partition by id_produto order by efetivo_em, lsn)
),

-- Evento que não mudou nada (ex.: UPDATE de coluna irrelevante) não abre versão.
mudancas as (
    select *
    from ativos
    where ordem = 1
        or preco_centavos is distinct from preco_anterior
        or custo_centavos is distinct from custo_anterior
        or nome_produto is distinct from nome_anterior
        or codigo_subitem_ipca is distinct from subitem_anterior
),

versoes as (
    select
        m.*,
        row_number() over (partition by m.id_produto order by m.efetivo_em, m.lsn) as versao,
        coalesce(
            lead(m.efetivo_em) over (partition by m.id_produto order by m.efetivo_em, m.lsn),
            e.excluido_em
        ) as vigencia_fim
    from mudancas as m
    left join exclusoes as e using (id_produto)
)

select
    id_produto || '-' || versao as id_versao_preco,
    id_produto,
    cast(versao as smallint) as versao,
    id_lojista,
    nome_produto,
    codigo_subitem_ipca,
    cast(preco_centavos / 100.0 as decimal(14, 2)) as preco_brl,
    cast(custo_centavos / 100.0 as decimal(14, 2)) as custo_brl,
    evento as evento_de_abertura,
    efetivo_em as vigencia_inicio,
    vigencia_fim,
    vigencia_fim is null as versao_atual
from versoes
