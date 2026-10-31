-- 0005 — Vitrine do resultado: o schema `serie`, cópia das tabelas da Gold que o painel consulta.
--
-- O Postgres não calcula nada aqui: quem preenche é inflatrack.reverse_etl.exportar_serie, que
-- apaga e insere as linhas SEM recriar a tabela. Por isso as tabelas nascem nesta migration: o
-- índice e as permissões continuam valendo depois de cada cópia. As colunas precisam estar na
-- mesma ordem dos modelos do dbt; se divergirem, a cópia falha sem alterar nada.
--
-- `serie` não tem chave primária: o grão é garantido e testado na Gold (dbt), e uma chave aqui
-- seria mais um índice para manter a cada recarga. O CDC não lê este schema (0004).

begin;

create schema if not exists serie;

create table if not exists serie.dim_calendario (
    mes_referencia    date primary key,
    ano               smallint not null,
    mes               smallint not null,
    trimestre         smallint not null,
    semestre          smallint not null,
    ano_mes           text     not null,
    trimestre_inicio  date     not null,
    ultimo_dia        date     not null
);

create table serie.dim_localidade (
    codigo_localidade  integer primary key,
    nome_localidade    text not null,
    tipo_localidade    text not null,
    uf                 text
);

create table serie.dim_cesta_ipca_scd2 (
    id_versao_cesta         text primary key,
    indice                  text     not null,
    codigo_categoria        text     not null,
    agregado                smallint not null,
    estrutura_cesta         text     not null,
    versao                  smallint not null,
    nome_categoria          text     not null,
    codigo_pai              text,
    nivel_categoria         text     not null,
    vigencia_inicio         date     not null,
    vigencia_fim            date,
    versao_atual            boolean  not null,
    peso_brasil_inicio_pct  numeric(12, 4),
    peso_brasil_fim_pct     numeric(12, 4)
);

create table serie.fct_inflacao_mensal (
    indice                      text     not null,
    codigo_categoria            text     not null,
    codigo_localidade           integer  not null,
    mes_referencia              date     not null,
    id_versao_cesta             text     not null,
    nivel_categoria             text     not null,
    agregado_origem             smallint not null,
    variacao_mensal_pct         numeric(12, 4),
    variacao_acum_ano_pct       numeric(12, 4),
    variacao_acum_12m_pct       numeric(12, 4),
    origem_acum_12m             text,
    peso_mensal_pct             numeric(12, 4),
    numero_indice               numeric(28, 13),
    media_movel_3m_pct          numeric(12, 4),
    media_movel_6m_pct          numeric(12, 4),
    media_movel_12m_pct         numeric(12, 4),
    desvio_padrao_12m_pct       numeric(12, 4),
    variacao_mensal_lag_1m_pct  numeric(12, 4),
    variacao_mensal_lag_2m_pct  numeric(12, 4),
    variacao_mensal_lag_3m_pct  numeric(12, 4)
);
comment on table serie.fct_inflacao_mensal is
    'Uma linha por índice x categoria da cesta x localidade x mês. Cópia de gold.fct_inflacao_mensal.';

-- O índice medido no EXPLAIN (docs/evidencias/e3/explain_serie.md). Serve à pergunta mais
-- frequente do lojista: a série de uma categoria na praça dele, do mês mais recente para trás.
create index fct_inflacao_mensal_consulta_idx on serie.fct_inflacao_mensal (
    codigo_categoria, codigo_localidade, indice, mes_referencia desc
);

create table serie.dim_produto_preco_scd2 (
    id_versao_preco      text primary key,
    id_produto           bigint        not null,
    versao               smallint      not null,
    id_lojista           bigint        not null,
    nome_produto         text          not null,
    codigo_subitem_ipca  text          not null,
    preco_brl            numeric(14, 2) not null,
    custo_brl            numeric(14, 2) not null,
    evento_de_abertura   text          not null,
    vigencia_inicio      timestamptz   not null,
    vigencia_fim         timestamptz,
    versao_atual         boolean       not null
);

create table serie.fct_reajuste_lojista (
    id_produto                    bigint   not null,
    mes_referencia                date     not null,
    id_versao_preco               text     not null,
    id_lojista                    bigint   not null,
    hash_estabelecimento          text     not null,
    codigo_localidade             integer  not null,
    codigo_subitem_ipca           text     not null,
    preco_brl                     numeric(14, 2) not null,
    custo_brl                     numeric(14, 2) not null,
    quantidade_vendida            numeric(14, 3),
    receita_brl                   numeric(14, 2),
    margem_pct                    numeric(12, 4),
    variacao_preco_mensal_pct     numeric(12, 4),
    ipca_mensal_pct               numeric(12, 4),
    origem_ipca                   text,
    mes_ipca_referencia           date,
    variacao_preco_12m_pct        numeric(12, 4),
    variacao_custo_12m_pct        numeric(12, 4),
    ipca_acum_12m_pct             numeric(12, 4),
    ipca_acum_desde_cadastro_pct  numeric(12, 4),
    defasagem_12m_pct             numeric(12, 4),
    reajuste_minimo_pct           numeric(12, 4)
);
comment on table serie.fct_reajuste_lojista is
    'Uma linha por produto do lojista x mês. Cópia de gold.fct_reajuste_lojista.';
create index fct_reajuste_lojista_lojista_idx
    on serie.fct_reajuste_lojista (id_lojista, mes_referencia desc);

-- Papéis sem login: quem conecta recebe o papel. Criar papel não aceita IF NOT EXISTS, e papel é
-- objeto do servidor, não do banco.
do $$
begin
    if not exists (select from pg_roles where rolname = 'inflatrack_pipeline') then
        create role inflatrack_pipeline nologin;
    end if;
    if not exists (select from pg_roles where rolname = 'lojista_app') then
        create role lojista_app nologin;
    end if;
    if not exists (select from pg_roles where rolname = 'metabase_leitor') then
        create role metabase_leitor nologin;
    end if;
end;
$$;

revoke all on schema serie from public;
grant usage on schema serie to inflatrack_pipeline, lojista_app, metabase_leitor;

-- Só o pipeline escreve em `serie` (PLAN_E3_E4.md, Seção 2.2).
grant select, insert, delete on all tables in schema serie to inflatrack_pipeline;

-- O painel lê tudo. Tabela nova que a cópia criar sozinha já nasce legível para ele.
grant select on all tables in schema serie to metabase_leitor;
alter default privileges in schema serie grant select on tables to metabase_leitor;
alter default privileges in schema serie grant select, insert, delete on tables to inflatrack_pipeline;

-- O lojista lê só o que é público. As duas tabelas do lojista ficam de fora até a E4 ter RLS por
-- estabelecimento: com um GRANT aqui, cada loja leria os preços de todas as outras.
grant select on serie.dim_calendario, serie.dim_localidade, serie.dim_cesta_ipca_scd2,
    serie.fct_inflacao_mensal to lojista_app;

commit;
