-- 0005 — Schema serie: a vitrine servida ao painel do Metabase e ao lojista.
--
-- O DuckDB calcula e o Postgres serve. O Metabase lê exclusivamente o Postgres
-- (schema `serie`), populado a partir da camada Gold via reverse ETL.
-- O índice cobrindo viabiliza consultas analíticas com Index-Only Scan.

begin;

create schema if not exists serie;

create table if not exists serie.serie_mensal (
    id                    bigint generated always as identity primary key,
    id_fonte              smallint not null,
    codigo_classificacao  text     not null,
    codigo_localidade     integer  not null,
    codigo_variavel       smallint not null,
    mes_referencia        date     not null,
    valor                 numeric(16, 7) not null,
    ingerido_em           timestamptz    not null default now()
);

comment on table serie.serie_mensal is
    'Série histórica consolidada servida ao Metabase e ao comerciante.';

-- Índice cobrindo otimizado para consultas por indicador + localidade + período:
create index if not exists idx_serie_mensal_covering
on serie.serie_mensal (codigo_classificacao, codigo_localidade, codigo_variavel, mes_referencia desc)
include (valor);

commit;
