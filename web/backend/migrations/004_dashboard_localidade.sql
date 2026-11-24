-- 004 — Dashboard de inflação por praça, pronto para o site (Supabase).
--
-- Quem escreve: inflatrack.reverse_etl.publicar_site (ativo site_supabase, que roda no
-- dashboard_job e no predicao_job), na mesma transação das tabelas da 003.
-- Quem lê: o backend do site (GET /dashboard) e a Felicia. O backend só recorta o período.
-- Uma linha por praça, com o histórico inteiro em `dados` (cerca de 25 KB cada, 17 praças).
-- Sem preço e sem dado de usuário (ADR 0004).
--
-- Como aplicar: depois da 003, cole no SQL Editor do Supabase. É reexecutável.

create table if not exists dashboard_localidade (
    codigo_localidade  integer     primary key,
    dados              jsonb       not null,
    publicado_em       timestamptz not null default now()
);
comment on table dashboard_localidade is
    'Dashboard de inflação de cada praça (KPIs, setores, praças, histórico, sazonalidade, poder de compra), calculado no ambiente local.';

alter table dashboard_localidade enable row level security;
drop policy if exists leitura_publica on dashboard_localidade;
create policy leitura_publica on dashboard_localidade for select to anon, authenticated using (true);
revoke all on dashboard_localidade from anon, authenticated;
grant select on dashboard_localidade to anon, authenticated;
