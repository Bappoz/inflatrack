-- 0002 — Lado transacional: o que a plataforma sabe e o IBGE não.
--
-- É aqui que a E1 tem escrita de verdade: aplicar um reajuste insere em
-- `reajuste` dentro de uma transação. O preço corrente NÃO é uma coluna
-- atualizável — é derivado do último reajuste (view produto_preco_atual).
-- Guardar só o preço atual responderia "quanto custa hoje" e destruiria
-- "quanto eu deveria ter reajustado e não reajustei", que é o problema do projeto.

begin;

create table lojista (
    id                 bigint  generated always as identity primary key,
    nome_fantasia      text    not null check (length(trim(nome_fantasia)) > 0),
    cnpj               char(14) not null unique check (cnpj ~ '^[0-9]{14}$'),
    codigo_localidade  integer not null references localidade (codigo_ibge) on delete restrict,
    codigo_grupo_ipca  text    not null references classificacao (codigo)   on delete restrict,
    criado_em          timestamptz not null default now()
);
comment on column lojista.cnpj is
    'CNPJ de MEI se confunde com a pessoa física: tratar como dado pessoal (LGPD) e não expor em recorte analítico.';
comment on column lojista.codigo_localidade is
    'A praça a que o lojista se compara. Só as 17 localidades medidas pelo IPCA são válidas.';

create table produto (
    id                      bigint  generated always as identity primary key,
    id_lojista              bigint  not null references lojista (id) on delete cascade,
    nome                    text    not null check (length(trim(nome)) > 0),
    preco_inicial_centavos  integer not null check (preco_inicial_centavos > 0),
    custo_inicial_centavos  integer not null check (custo_inicial_centavos >= 0),
    codigo_subitem_ipca     text    not null references classificacao (codigo) on delete restrict,
    criado_em               timestamptz not null default now(),
    unique (id_lojista, nome)
);
comment on column produto.codigo_subitem_ipca is
    'O de-para produto -> subitem do IPCA. Se essa FK não for garantida pelo banco, o painel calcula reajuste sobre a categoria errada e nada acusa o erro.';
create index produto_subitem_idx on produto (codigo_subitem_ipca);

create table reajuste (
    id                       bigint  generated always as identity primary key,
    id_produto               bigint  not null references produto (id) on delete cascade,
    preco_anterior_centavos  integer not null check (preco_anterior_centavos > 0),
    preco_novo_centavos      integer not null check (preco_novo_centavos > 0),
    ipca_acumulado_ref       numeric(8, 4),
    mes_referencia_ipca      date,
    motivo                   text    not null,
    aplicado_em              timestamptz not null default now(),
    constraint precos_diferentes check (preco_novo_centavos <> preco_anterior_centavos)
);
create index reajuste_produto_idx on reajuste (id_produto, aplicado_em desc);

create view produto_preco_atual as
select p.id           as id_produto,
       p.id_lojista,
       p.nome,
       p.codigo_subitem_ipca,
       coalesce(r.preco_novo_centavos, p.preco_inicial_centavos) as preco_centavos,
       coalesce(r.aplicado_em, p.criado_em)                      as vigente_desde
from produto p
left join lateral (
    select preco_novo_centavos, aplicado_em
    from reajuste
    where id_produto = p.id
    order by aplicado_em desc
    limit 1
) r on true;

commit;
