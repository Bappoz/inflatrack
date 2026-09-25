-- 0004 — Tabela de referência macroeconômica: PIB da China (World Bank API)

begin;

create table if not exists pib_china (
    id                      bigint generated always as identity primary key,
    ano                     integer not null,
    crescimento_pib_pct    numeric(8, 4),
    pib_usd                numeric(20, 2),
    criado_em               timestamptz not null default clock_timestamp(),
    constraint pib_china_ano_unique unique (ano)
);

comment on table pib_china is
    'Serie historica do PIB da China (World Bank API) utilizada como variavel macroeconomica explicativa da demanda por commodities.';

commit;
