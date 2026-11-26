# Preços de atacadista no Postgres — design

Data: 2026-11-19 · Substitui o PR #21 (Cesta Básica PROCON)

## Por que

O modelo preditivo da E4 deve ajudar o lojista a decidir o reajuste do preço de venda
para acompanhar a variação dos seus custos. O custo do lojista é o preço que ele paga
no atacado. Falta ao projeto uma base com esses preços.

Regra do integrante: **preço de produto fica só no banco relacional**. Não passa por
Raw, Bronze (Delta/DuckDB), Silver nem Gold.

## Abordagens consideradas

1. **Atacadista simulado com histórico desde 2006**: preços gerados a partir do subitem
   do IPCA, com defasagem e ruído. Descartada: o modelo só reaprenderia a fórmula usada
   para gerar os dados.
2. **Coleta real a partir de agora** (site do Atacadão ou preço por nota fiscal):
   descartada para a E4, porque sem histórico não há o que treinar até 24/11.
   Fica como evolução.
3. **Escolhida: alvo real com tradução em R$.** O modelo aprende a variação do subitem
   do IPCA (real, desde 2006, já na Gold). O Postgres guarda só o preço atual de cada
   produto no atacadista. Na recomendação, o percentual previsto vira R$:
   `custo_previsto = preco_atacado_atual × (1 + variacao_prevista_subitem)`.

O PROCON foi descartado: não publica preços em formato de dados (só PDFs com parte
dos produtos).

## Objetivos

- Uma base relacional de preços de atacadista, ligada ao subitem do IPCA.
- Histórico de mudanças de preço sem `UPDATE`, no padrão das tabelas do lojista.
- Um caminho para carregar a tabela de preços do atacadista a partir de um CSV.

## Não objetivos

- O modelo preditivo e a `recomendacao_reajuste` (próximo trabalho, separado).
- Coleta automática de site ou API.

## Anti-objetivos

- Qualquer preço do atacadista aparecer no Delta, no DuckDB, no dbt ou na publicação
  do CDC.
- Dado inventado entrar sem o rótulo de fictício.

## Design

**Branch nova `feat/precos-atacadista` a partir da `main`.** O PR #21 é fechado com um
comentário que aponta para o novo e credita os conversores.

**Migration `migrations/0007_preco_atacadista.sql`, schema próprio `atacado`:**

| Tabela/visão | Conteúdo |
|---|---|
| `atacado.fornecedor` | `id`, `nome`, `codigo_localidade` (uma das 17 praças do IPCA), `ficticio boolean` |
| `atacado.produto` | `id`, `id_fornecedor`, `nome`, `unidade`, `codigo_subitem_ipca` (FK para `classificacao`, como `public.produto`), único por fornecedor e nome |
| `atacado.preco` | `id_produto`, `preco_centavos integer > 0`, `vigente_desde date`, `registrado_em`; insert-only pelo trigger `impede_update_em_historico()` da 0004 |
| `atacado.preco_atual` | visão com o último preço de cada produto |

- Schema separado deixa visível que nada ali entra no CDC (a publicação
  `inflatrack_cdc` lista tabelas de `public` uma a uma).
- Centavos em `integer`, como no resto do OLTP.

**Carga:** módulo `inflatrack.atacado.importar_tabela` lê um CSV de tabela de preços
(`produto;unidade;preco;codigo_subitem_ipca;vigente_desde`) e grava direto no
Postgres, só acrescentando preço quando ele muda. Reaproveita `_converter_valor` e
`_converter_data` do PR #21, movidos para um módulo comum. Receita `just atacado-importar`.

**Dados iniciais:** um atacadista fictício (`ficticio = true`) com cerca de 40 produtos
de alimentação, higiene e limpeza ligados aos subitens do IPCA, em
`data/atacado/tabela_exemplo.csv`. *Decisão da ferramenta*: fictício porque o lojista
também é, e uma coleta real única pode substituí-lo depois sem mudar o esquema.

**Uso pelo modelo (E4, fora deste trabalho):** o código de predição lê
`atacado.preco_atual` direto do Postgres no momento de recomendar; não copia para o
DuckDB.

**Documentação:** ADR `docs/adr/0004-preco-produto-so-relacional.md` com a regra e o
porquê; `PLAN_E3_E4.md` atualizado (camada 0 e a regra); dicionário em
`docs/dicionario/atacado.md`.

## Testes

- Integração (Postgres descartável): migration aplica; `UPDATE` em `atacado.preco` é
  barrado; FK do subitem barra código inválido; `preco_atual` devolve o mais recente;
  nenhuma tabela de `atacado` está em `pg_publication_tables`.
- Unitários do importador: formato brasileiro, data, preço repetido não gera linha,
  preço novo gera.
- Varredura: nenhum arquivo em `dbt/`, `bronze/` ou `loaders/` cita `atacado`.

## Fica para quem implementar

- A lista exata dos ~40 produtos e de seus subitens (conferir os códigos em `classificacao`).
- Nome do módulo comum dos conversores.
