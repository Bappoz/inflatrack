-- 0001 — Camada de referência: a estrutura que o IBGE publica.
--
-- A cesta do IPCA NÃO é estável. Entre jul/2006 e jul/2026 o IBGE fez duas
-- revisões de estrutura (POF 2008-2009 e POF 2017-2018) e, nelas:
--   * 43 subitens mudaram de NOME mantendo o MESMO CÓDIGO
--     (1111004 "Leite pasteurizado" -> "Leite longa vida";
--      3202028 "Microcomputador"    -> "Computador pessoal";
--      9101008 "Telefone celular"   -> "Plano de telefonia móvel")
--   * 111 subitens saíram e 103 entraram.
-- Por isso o nome vive em `classificacao_versao` com vigência, e não na
-- classificação. Guardar o nome junto do código partiria em duas a série de
-- todo subitem renomeado — silenciosamente. Ver docs/adr/0001.

begin;

create table fonte_agregado (
    id              smallint primary key,
    indice          text     not null check (indice in ('IPCA', 'INPC')),
    nome            text     not null,
    periodo_inicio  date     not null,
    periodo_fim     date,
    tem_acum_12m    boolean  not null,
    constraint fonte_periodo_coerente
        check (periodo_fim is null or periodo_fim >= periodo_inicio)
);
comment on table fonte_agregado is
    'Agregados do SIDRA que alimentam a plataforma. periodo_fim nulo = série viva.';
comment on column fonte_agregado.tem_acum_12m is
    'A tabela 2938 (2006-2011) não publica a variação acumulada em 12 meses; para esse período ela tem de ser derivada da variação mensal.';

create table variavel (
    codigo   smallint primary key,
    nome     text not null,
    unidade  text not null
);

create table localidade (
    codigo_ibge  integer primary key,
    nome         text    not null,
    tipo         text    not null check (tipo in ('pais', 'regiao_metropolitana', 'municipio')),
    uf           char(2)
);

-- Chave natural estável: um código de cesta, visto alguma vez em alguma fonte.
create table classificacao (
    codigo  text primary key,
    nivel   text not null check (nivel in ('geral', 'grupo', 'subgrupo', 'item', 'subitem'))
);
comment on table classificacao is
    'Hierarquia da cesta. O código do pai é prefixo do filho: 1 -> 11 -> 1101 -> 1101002.';

-- Dimensão de variação lenta (tipo 2) sobre a classificação.
create table classificacao_versao (
    id               bigint generated always as identity primary key,
    codigo           text     not null references classificacao (codigo) on delete restrict,
    id_fonte         smallint not null references fonte_agregado (id)   on delete restrict,
    nome             text     not null,
    codigo_pai       text              references classificacao (codigo) on delete restrict,
    vigencia_inicio  date     not null,
    vigencia_fim     date,
    unique (codigo, id_fonte),
    constraint versao_periodo_coerente
        check (vigencia_fim is null or vigencia_fim >= vigencia_inicio)
);
create index classificacao_versao_pai_idx on classificacao_versao (codigo_pai);

-- Tabela de fato. INSERT-ONLY por decisão explícita: o IBGE republica valor
-- revisado do mesmo mês e a plataforma precisa saber o que respondeu ao lojista
-- ANTES da revisão. Um UPDATE apagaria essa resposta.
create table observacao (
    id                    bigint   generated always as identity primary key,
    id_fonte              smallint not null references fonte_agregado (id)   on delete restrict,
    codigo_classificacao  text     not null references classificacao (codigo) on delete restrict,
    codigo_localidade     integer  not null references localidade (codigo_ibge) on delete restrict,
    codigo_variavel       smallint not null references variavel (codigo)     on delete restrict,
    mes_referencia        date     not null,
    valor                 numeric(16, 7) not null,
    ingerido_em           timestamptz    not null default now(),
    constraint mes_referencia_no_dia_1
        check (extract(day from mes_referencia) = 1)
);

-- Idempotência da carga: reexecutar com o mesmo dado é no-op; se o IBGE revisar
-- o valor de um mês já carregado, a revisão entra como linha NOVA e a anterior fica.
create unique index observacao_versao_uk on observacao (
    id_fonte, codigo_classificacao, codigo_localidade, codigo_variavel, mes_referencia, valor
);
-- Índice das perguntas 1, 4 e 5: filtra por subitem + praça + variável, ordena por mês.
create index observacao_consulta_idx on observacao (
    codigo_classificacao, codigo_localidade, codigo_variavel, mes_referencia desc
);

commit;
