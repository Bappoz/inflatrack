# 0004 — Preço de produto fica só no banco relacional

- **Status:** aceito e implementado (migration `0007_preco_atacadista.sql`)
- **Data:** 2026-11-19
- **Decisores:** Squad InflaTrack

## Contexto

O modelo preditivo da E4 deve ajudar o lojista a decidir o reajuste do preço de venda para
acompanhar a variação dos seus custos. O custo do lojista é o preço que ele paga no atacado, e o
projeto não tinha nenhuma base com esses preços.

O PR #21 propôs a Cesta Básica do PROCON como essa base, pelo caminho das fontes analíticas:
Raw, Bronze em Delta, DuckDB, `stg`/`int` no dbt e uma fato na Gold. Dois problemas:

- a Squad decidiu que **preço de produto não passa pelas camadas Bronze, Silver e Gold**: ele fica
  só no banco relacional;
- o PROCON não publica preços como dado aberto. Há só relatórios em PDF ou DOCX por órgão (o
  Procon-SP traz, em convênio com o DIEESE, o preço de parte dos 39 produtos em gráficos e texto),
  e o CSV que o PR esperava não existe.

## Abordagens consideradas

1. **Atacadista simulado com histórico desde 2006**, gerado a partir do subitem do IPCA. Descartada:
   o modelo só reaprenderia a fórmula usada para gerar os dados.
2. **Coleta real a partir de agora** (loja online de um atacadista ou preço por nota fiscal).
   Descartada para a E4: sem histórico, não há o que treinar até a entrega. Fica como evolução.
3. **Escolhida: alvo real com tradução em R$.** O modelo aprende a variação do subitem do IPCA,
   real e com histórico desde 2006 na Gold. O Postgres guarda o preço de cada produto no
   atacadista. Na recomendação, o percentual previsto vira valor:
   `custo_previsto = preco_atual × (1 + variacao_prevista_do_subitem)`.

## Decisão

1. Preços de atacadista ficam no schema `atacado` do Postgres (`fornecedor`, `produto`, `preco`
   insert-only e a visão `preco_atual`), ligados ao subitem do IPCA pela mesma FK de
   `public.produto`.
2. Nenhuma tabela de `atacado` entra na publicação `inflatrack_cdc`, e nenhum código de `dbt/`,
   `src/inflatrack/bronze/`, `src/inflatrack/loaders/` ou `orchestration/` cita o schema.
   `tests/unit/test_regra_preco_relacional.py` e `tests/integration/test_atacado_schema.py`
   guardam as duas regras.
3. A carga é `inflatrack.atacado.importar_tabela` (`just atacado-importar`): lê o CSV e grava
   direto no Postgres, sem Raw nem Delta.
4. Enquanto não houver coleta real, a base tem um atacadista **fictício** (`ficticio = true`),
   como o lojista de demonstração.

## Consequências

- O preço do atacadista não tem histórico analítico nem linhagem no dbt; quem precisar dele lê o
  Postgres.
- O código de predição da E4 lê `atacado.preco_atual` na hora de recomendar e não o copia para o
  DuckDB.
- Os preços do **lojista** (`public.produto`, `reajuste`, `reajuste_custo`) continuam saindo pelo
  CDC para a Bronze, como definido na E3. Esta decisão não muda esse caminho; se a regra também
  valer para eles, isso exige um ADR próprio.
- Uma coleta real futura entra pelo mesmo importador, com outro fornecedor e `ficticio = false`.
