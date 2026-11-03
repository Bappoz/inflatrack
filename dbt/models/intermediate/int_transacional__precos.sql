-- Linha do tempo de cada produto: uma linha por evento, com o estado completo depois dele.
--
-- A ordem é a do NEGÓCIO (`aplicado_em`), e não a de captura: um reajuste de janeiro registrado
-- depois do de março entra entre os dois (chegada atrasada), mesmo tendo LSN maior. Em evento sem
-- data de negócio (renomear, excluir), vale a hora do commit.
--
-- `reajuste` e `reajuste_custo` são insert-only: o DELETE deles só existe em cascata, quando o
-- produto é apagado, e o histórico do produto continua valendo até a exclusão.

with mudancas as (
    select * from {{ ref('stg_transacional__mudanca') }}
    where operacao in ('r', 'I', 'U', 'D')
),

-- Uma linha pode estar na foto inicial e também como evento, se mudou entre o slot e a foto.
reajustes as (
    select
        id_registro,
        lsn,
        cast(json_extract_string(depois, '$.id_produto') as bigint) as id_produto,
        cast(json_extract_string(depois, '$.aplicado_em') as timestamptz) as efetivo_em,
        cast(json_extract_string(depois, '$.preco_novo_centavos') as integer) as preco_centavos
    from mudancas
    where tabela = 'reajuste' and operacao in ('r', 'I')
    qualify row_number() over (partition by id_registro order by lsn) = 1
),

reajustes_custo as (
    select
        id_registro,
        lsn,
        cast(json_extract_string(depois, '$.id_produto') as bigint) as id_produto,
        cast(json_extract_string(depois, '$.aplicado_em') as timestamptz) as efetivo_em,
        cast(json_extract_string(depois, '$.custo_novo_centavos') as integer) as custo_centavos
    from mudancas
    where tabela = 'reajuste_custo' and operacao in ('r', 'I')
    qualify row_number() over (partition by id_registro order by lsn) = 1
),

eventos as (
    -- Cadastro: o estado inicial, na data de criação.
    select
        id_registro as id_produto,
        cast(json_extract_string(depois, '$.criado_em') as timestamptz) as efetivo_em,
        lsn,
        'cadastro' as evento,
        cast(json_extract_string(depois, '$.id_lojista') as bigint) as id_lojista,
        json_extract_string(depois, '$.nome') as nome_produto,
        json_extract_string(depois, '$.codigo_subitem_ipca') as codigo_subitem_ipca,
        cast(json_extract_string(depois, '$.preco_inicial_centavos') as integer) as preco_centavos,
        cast(json_extract_string(depois, '$.custo_inicial_centavos') as integer) as custo_centavos,
        false as excluido
    from mudancas
    where tabela = 'produto' and operacao in ('r', 'I')
    qualify row_number() over (partition by id_registro order by lsn) = 1

    union all

    -- Alteração de cadastro. O preço e o custo correntes nunca mudam aqui: vêm dos reajustes.
    select
        id_registro,
        commit_em,
        lsn,
        'alteracao',
        cast(json_extract_string(depois, '$.id_lojista') as bigint),
        json_extract_string(depois, '$.nome'),
        json_extract_string(depois, '$.codigo_subitem_ipca'),
        null,
        null,
        false
    from mudancas
    where tabela = 'produto' and operacao = 'U'

    union all

    select id_registro, commit_em, lsn, 'exclusao', null, null, null, null, null, true
    from mudancas
    where tabela = 'produto' and operacao = 'D'

    union all

    select id_produto, efetivo_em, lsn, 'reajuste', null, null, null, preco_centavos, null, false
    from reajustes

    union all

    select id_produto, efetivo_em, lsn, 'custo', null, null, null, null, custo_centavos, false
    from reajustes_custo
),

estados as (
    select
        id_produto,
        efetivo_em,
        lsn,
        evento,
        last_value(id_lojista ignore nulls) over ate_aqui as id_lojista,
        last_value(nome_produto ignore nulls) over ate_aqui as nome_produto,
        last_value(codigo_subitem_ipca ignore nulls) over ate_aqui as codigo_subitem_ipca,
        last_value(preco_centavos ignore nulls) over ate_aqui as preco_centavos,
        last_value(custo_centavos ignore nulls) over ate_aqui as custo_centavos,
        bool_or(excluido) over ate_aqui as excluido
    from eventos
    window ate_aqui as (
        partition by id_produto
        order by efetivo_em, lsn
        rows between unbounded preceding and current row
    )
)

-- Dois eventos no mesmo instante viram um só estado: o último deles.
select *
from estados
qualify row_number() over (partition by id_produto, efetivo_em order by lsn desc) = 1
