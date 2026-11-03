-- 0004 — Evolução do OLTP para a E3: precisão do 1737, vigência da cesta, custo e vendas do
-- lojista, e o que o CDC precisa para enxergar as mudanças. Em volume já existente:
-- `just migrar 0004_evolucao_oltp_cdc_e_consultas.sql` e reinicie o banco (wal_level=logical).

begin;

-- O número-índice do 1737 chega a 0.0000000076183 (dez/1979): numeric(16,7) arredondava para
-- zero. O índice único inclui o valor, então recarregar o 1737 grava o valor exato como linha
-- nova; a anterior fica, e vale a mais recente (ingerido_em), como em toda revisão.
alter table observacao alter column valor type numeric(28, 13);

-- SCD tipo 2 de verdade: antes, renomear um subitem sobrescrevia o nome antigo, porque só cabia
-- uma linha por (codigo, id_fonte). Agora cabe uma por vigência, e só uma pode estar aberta.
alter table classificacao_versao drop constraint classificacao_versao_codigo_id_fonte_key;
alter table classificacao_versao
    add constraint classificacao_versao_vigencia_uk unique (codigo, id_fonte, vigencia_inicio);
create unique index classificacao_versao_aberta_uk
    on classificacao_versao (codigo, id_fonte) where vigencia_fim is null;

-- O custo muda sem o preço mudar (a restrição `precos_diferentes` de `reajuste` proíbe evento
-- sem mudança de preço), então cada alteração de custo é um evento próprio.
create table reajuste_custo (
    id                       bigint  generated always as identity primary key,
    id_produto               bigint  not null references produto (id) on delete cascade,
    custo_anterior_centavos  integer not null check (custo_anterior_centavos >= 0),
    custo_novo_centavos      integer not null check (custo_novo_centavos >= 0),
    motivo                   text    not null,
    aplicado_em              timestamptz not null default now(),
    constraint custos_diferentes check (custo_novo_centavos <> custo_anterior_centavos)
);
create index reajuste_custo_produto_idx on reajuste_custo (id_produto, aplicado_em desc);

-- Insert-only como o resto do histórico: corrigir uma venda é inserir outra linha para o mesmo
-- mês, e vale a de `registrado_em` mais recente (a Silver escolhe).
create table venda_mensal (
    id               bigint generated always as identity primary key,
    id_produto       bigint not null references produto (id) on delete cascade,
    mes_referencia   date   not null,
    quantidade       numeric(14, 3) not null check (quantidade >= 0),
    receita_centavos bigint not null check (receita_centavos >= 0),
    registrado_em    timestamptz not null default now(),
    constraint venda_mes_no_dia_1 check (extract(day from mes_referencia) = 1),
    unique (id_produto, mes_referencia, registrado_em)
);
comment on table venda_mensal is
    'Insert-only: uma correção é uma linha nova para o mesmo mês; vale a de registrado_em mais recente.';

-- O histórico é insert-only por decisão (0001, 0002), e agora o banco garante. DELETE continua
-- possível: apagar o lojista (LGPD) precisa levar o histórico dele em cascata.
create function impede_update_em_historico() returns trigger
    language plpgsql
    set search_path = ''
as $$
begin
    raise exception '% é insert-only: registre um novo evento em vez de alterar', tg_table_name
        using errcode = 'restrict_violation';
end;
$$;

create trigger reajuste_insert_only before update on reajuste
    for each row execute function impede_update_em_historico();
create trigger reajuste_custo_insert_only before update on reajuste_custo
    for each row execute function impede_update_em_historico();
create trigger venda_mensal_insert_only before update on venda_mensal
    for each row execute function impede_update_em_historico();
create trigger observacao_insert_only before update on observacao
    for each row execute function impede_update_em_historico();

-- CDC: com REPLICA IDENTITY FULL, UPDATE e DELETE publicam a linha anterior inteira, e não só a
-- chave. A publicação lista as tabelas uma a uma: nunca `serie` (sem laço de retroalimentação),
-- nunca a referência do IBGE. `produto_preco_atual` é view e não gera eventos: o preço corrente
-- deriva de `reajuste`, que é publicado.
alter table lojista        replica identity full;
alter table produto        replica identity full;
alter table reajuste       replica identity full;
alter table reajuste_custo replica identity full;
alter table venda_mensal   replica identity full;

create publication inflatrack_cdc
    for table lojista, produto, reajuste, reajuste_custo, venda_mensal;

commit;
