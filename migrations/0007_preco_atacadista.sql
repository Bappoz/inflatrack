-- 0007 — Preços de atacadista: o que o lojista paga pela mercadoria (ADR 0004).
--
-- Preço de produto fica SÓ aqui, no relacional. Não vai para Raw, Bronze (Delta/DuckDB), Silver
-- nem Gold: por isso o schema é próprio e nenhuma tabela dele entra na publicação inflatrack_cdc.
-- O modelo preditivo da E4 aprende a variação do subitem do IPCA (Gold) e, na hora de recomendar,
-- lê atacado.preco_atual direto daqui para traduzir o percentual previsto em R$.
--
-- Quem preenche: inflatrack.atacado.importar_tabela (`just atacado-importar`).
-- Reexecutável: tudo é `if not exists` / `or replace`. Num volume existente:
-- `just migrar 0007_preco_atacadista.sql`.

begin;

create schema if not exists atacado;

create table if not exists atacado.fornecedor (
    id                 bigint  generated always as identity primary key,
    nome               text    not null unique check (length(trim(nome)) > 0),
    codigo_localidade  integer not null,
    ficticio           boolean not null default false,
    criado_em          timestamptz not null default now()
);
comment on table atacado.fornecedor is
    'Atacadista de quem o lojista compra. Dado inventado leva ficticio = true.';
comment on column atacado.fornecedor.codigo_localidade is
    'Praça do IPCA onde o atacadista vende (mesmos códigos de lojista.codigo_localidade).';

create table if not exists atacado.produto (
    id                   bigint generated always as identity primary key,
    id_fornecedor        bigint not null references atacado.fornecedor (id) on delete cascade,
    nome                 text   not null check (length(trim(nome)) > 0),
    unidade              text   not null check (length(trim(unidade)) > 0),
    codigo_subitem_ipca  text   not null references classificacao (codigo) on delete restrict,
    criado_em            timestamptz not null default now(),
    unique (id_fornecedor, nome)
);
comment on column atacado.produto.codigo_subitem_ipca is
    'Subitem do IPCA cuja variação o modelo prevê para este produto.';
create index if not exists atacado_produto_subitem_idx on atacado.produto (codigo_subitem_ipca);

-- Insert-only: cada mudança de preço é uma linha nova, como reajuste_custo (0004).
create table if not exists atacado.preco (
    id              bigint  generated always as identity primary key,
    id_produto      bigint  not null references atacado.produto (id) on delete cascade,
    preco_centavos  integer not null check (preco_centavos > 0),
    vigente_desde   date    not null,
    registrado_em   timestamptz not null default now(),
    unique (id_produto, vigente_desde)
);
create index if not exists atacado_preco_produto_idx
    on atacado.preco (id_produto, vigente_desde desc);

drop trigger if exists preco_insert_only on atacado.preco;
create trigger preco_insert_only before update on atacado.preco
    for each row execute function impede_update_em_historico();

create or replace view atacado.preco_atual as
select distinct on (pr.id_produto)
       pr.id_produto,
       p.id_fornecedor,
       p.nome as produto,
       p.unidade,
       p.codigo_subitem_ipca,
       pr.preco_centavos,
       pr.vigente_desde
from atacado.preco as pr
join atacado.produto as p on p.id = pr.id_produto
where pr.vigente_desde <= current_date
order by pr.id_produto, pr.vigente_desde desc;
comment on view atacado.preco_atual is
    'Preço que vale hoje para cada produto do atacadista. Tabela anunciada com data futura só entra na data.';

commit;
