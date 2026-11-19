# Preços de Atacadista — Dicionário de Dados

## Contexto

O que o lojista paga pela mercadoria. O modelo preditivo da E4 prevê a variação do subitem do IPCA
de cada produto e usa o preço daqui para traduzir esse percentual em R$.

Pelo [ADR 0004](../adr/0004-preco-produto-so-relacional.md), estes preços ficam **só no Postgres**:
não vão para Raw, Bronze, Silver nem Gold, e nenhuma tabela do schema entra na publicação do CDC.
Esquema definido em `migrations/0007_preco_atacadista.sql`.

!!! warning "Dado fictício"
    Hoje a base tem um único atacadista inventado (`Atacadista Exemplo`, `ficticio = true`), com 45
    produtos de alimentação, limpeza e higiene em `data/atacado/tabela_exemplo.csv`.

## Entidades

### atacado.fornecedor

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | bigint (PK) | Chave substituta |
| `nome` | text | Único; não pode ser vazio |
| `codigo_localidade` | integer | Praça do IPCA onde o atacadista vende |
| `ficticio` | boolean | `true` para dado inventado |
| `criado_em` | timestamptz | Quando foi cadastrado |

### atacado.produto

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | bigint (PK) | Chave substituta |
| `id_fornecedor` | bigint (FK) | Atacadista; apagar o fornecedor apaga seus produtos |
| `nome` | text | Único por fornecedor |
| `unidade` | text | Embalagem vendida no atacado (ex.: `fardo 6 x 5 kg`) |
| `codigo_subitem_ipca` | text (FK `classificacao`) | Subitem do IPCA cuja variação o modelo prevê |
| `criado_em` | timestamptz | Quando foi cadastrado |

### atacado.preco

Insert-only: um `UPDATE` é barrado pelo trigger `impede_update_em_historico()`. Cada mudança de
preço é uma linha nova.

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | bigint (PK) | Chave substituta |
| `id_produto` | bigint (FK) | Produto do atacadista |
| `preco_centavos` | integer | Preço da embalagem em centavos; maior que zero |
| `vigente_desde` | date | A partir de quando vale; único por produto |
| `registrado_em` | timestamptz | Quando a linha foi gravada |

### atacado.preco_atual (visão)

O último preço (`vigente_desde` mais recente) de cada produto, com `produto`, `unidade`,
`codigo_subitem_ipca` e `id_fornecedor`.

## Carga

```bash
just migrar 0007_preco_atacadista.sql   # só num volume que já existia
just atacado-importar                   # atacadista fictício de exemplo
just atacado-importar tabela.csv "Atacadista Real" ""   # real: sem --ficticio
```

O CSV tem o cabeçalho `produto;unidade;preco;codigo_subitem_ipca;vigente_desde`, em UTF-8 (no
Excel: "CSV UTF-8"). Aceita `;` ou `,`; separado por `,`, o preço com vírgula decimal precisa estar
entre aspas. Preço em formato brasileiro (`R$ 1.234,56`), com no máximo duas casas decimais, e data
`AAAA-MM-DD` ou `DD/MM/AAAA`. Regras:

- o arquivo é validado inteiro antes de gravar, e um erro em qualquer linha não grava nada;
- reimportar não duplica nada, e corrigir um preço exige uma data nova;
- um produto já cadastrado não muda de unidade nem de subitem: embalagem nova é produto novo;
- um fornecedor já cadastrado não muda de praça nem de rótulo `ficticio`;
- os subitens precisam existir em `classificacao` (carga do IPCA);
- `preco_atual` só mostra preços com `vigente_desde` até hoje: uma tabela anunciada com data futura
  entra na data.

## Exemplo de consulta

Preço atual do atacadista para os produtos de um subitem:

```sql
select produto, unidade, preco_centavos / 100.0 as preco_reais, vigente_desde
from atacado.preco_atual
where codigo_subitem_ipca = '1101002';
```
