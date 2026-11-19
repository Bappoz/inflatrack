-- 003 — Tabelas que o InflaTrack publica para o site e o agente (Supabase).
--
-- Quem escreve: o ambiente local da Squad, por inflatrack.reverse_etl.publicar_site (ativo
-- site_supabase do predicao_job, ou `just publicar-site`), com a conexão do dono do projeto.
-- Cada publicação apaga e reescreve as cinco tabelas numa transação só: nada fica fora da janela.
-- Quem lê: o site e o agente, com a chave pública (anon) ou de usuário logado (authenticated).
-- Nenhum preço e nenhum dado de usuário vem para cá: o site faz preço x (1 + variação) com o
-- valor que a pessoa digita, sem gravar (ADR 0004).
--
-- Como aplicar: cole no SQL Editor do Supabase. É reexecutável (if not exists / drop if exists)
-- e não abre transação própria. Sem prefixo de schema: no Supabase o search_path é `public`.

create table if not exists previsao_subitem (
    codigo_localidade      integer          not null,
    codigo_subitem         text             not null,
    mes_base               date             not null,
    mes_previsto           date             not null,
    variacao_prevista_pct  double precision not null,
    erro_tipico_pct        double precision not null check (erro_tipico_pct >= 0),
    gerado_em              timestamptz      not null,
    primary key (codigo_localidade, codigo_subitem)
);
comment on table previsao_subitem is
    'Variação prevista do subitem do IPCA no mês seguinte ao último divulgado, por praça. O site mostra preço x (1 + variação), com a faixa de +/- erro_tipico_pct.';

create table if not exists subitem (
    codigo_subitem  text primary key,
    nome            text not null,
    codigo_grupo    text not null,
    nome_grupo      text not null
);

create table if not exists uf_praca (
    uf                 char(2) primary key,
    codigo_localidade  integer not null,
    nome_praca         text    not null
);
comment on table uf_praca is 'Praça do IPCA de cada UF. UF sem praça no IPCA usa o Brasil (1).';

create table if not exists resumo_subitem (
    codigo_localidade    integer          not null,
    codigo_subitem       text             not null,
    mes_referencia       date             not null,
    variacao_mensal_pct  double precision,
    variacao_12m_pct     double precision,
    primary key (codigo_localidade, codigo_subitem)
);
comment on table resumo_subitem is 'IPCA do último mês divulgado, por praça e subitem: o mês e 12 meses.';

create table if not exists painel_grafico (
    id            text        primary key,
    titulo        text        not null,
    grafico       text        not null,
    eixo_x        text,
    eixo_y        jsonb       not null,
    linhas        jsonb       not null,
    ate_o_mes     text,
    publicado_em  timestamptz not null default now()
);
comment on table painel_grafico is
    'Resultado pronto de cada gráfico do painel do lojista (scripts/sql/metabase/painel.toml): o site só desenha.';

-- Leitura pública, escrita só pelo dono (o ambiente local). Sem política de escrita, o RLS barra
-- insert, update e delete de anon e authenticated mesmo que alguém conceda o privilégio depois.
alter table previsao_subitem enable row level security;
alter table subitem          enable row level security;
alter table uf_praca         enable row level security;
alter table resumo_subitem   enable row level security;
alter table painel_grafico   enable row level security;

drop policy if exists leitura_publica on previsao_subitem;
drop policy if exists leitura_publica on subitem;
drop policy if exists leitura_publica on uf_praca;
drop policy if exists leitura_publica on resumo_subitem;
drop policy if exists leitura_publica on painel_grafico;
create policy leitura_publica on previsao_subitem for select to anon, authenticated using (true);
create policy leitura_publica on subitem          for select to anon, authenticated using (true);
create policy leitura_publica on uf_praca         for select to anon, authenticated using (true);
create policy leitura_publica on resumo_subitem   for select to anon, authenticated using (true);
create policy leitura_publica on painel_grafico   for select to anon, authenticated using (true);

revoke all on previsao_subitem, subitem, uf_praca, resumo_subitem, painel_grafico
    from anon, authenticated;
grant select on previsao_subitem, subitem, uf_praca, resumo_subitem, painel_grafico
    to anon, authenticated;
