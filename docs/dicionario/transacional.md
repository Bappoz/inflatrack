# Transacional (Lojista) — Dicionário de Dados

## Contexto

Tabelas do lado próprio do InflaTrack: o lojista, o que ele vende e os reajustes que aplica. Diferente da referência do IBGE, esse lado tem escrita de verdade — aplicar um reajuste é a única operação do sistema que exige transação com A, C e I garantidas. Esquema definido em `migrations/0002_lojista.sql`.

A ponte entre este lado e a referência pública é a FK `produto.codigo_subitem_ipca`, que aponta para `classificacao` (ver [dicionário do SIDRA](sidra.md)).

!!! warning "Dado pessoal (LGPD)"
    `lojista.cnpj` é tratado como dado pessoal: CNPJ de MEI se confunde com a pessoa física. Não é exposto em nenhum recorte analítico.

## Modelo Conceitual

<div class="diagrama">
--8<-- "docs/assets/diagramas/esquema-transacional.svg"
</div>

Em coral, as duas chaves que apagam em cascata: remover um lojista remove seus produtos, e remover um produto remove seus reajustes. `localidade` e `classificacao` são as tabelas de referência do IPCA, mostradas só com a chave.

## Entidades

### lojista

O comerciante que consulta e aplica reajuste.

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | bigint (PK) | Chave substituta |
| `nome_fantasia` | text | Nome do estabelecimento; não pode ser vazio |
| `cnpj` | char(14) | Chave natural única; dado pessoal (LGPD) |
| `codigo_localidade` | integer (FK `localidade`) | A praça a que o lojista se compara — só uma das 17 localidades medidas pelo IPCA |
| `codigo_grupo_ipca` | text (FK `classificacao`) | Setor principal do lojista |
| `criado_em` | timestamptz | Data de cadastro |

### produto

Um item que o lojista comercializa, ligado ao subitem do IPCA que melhor o representa.

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | bigint (PK) | Chave substituta |
| `id_lojista` | bigint (FK `lojista`) | Dono do produto |
| `nome` | text | Nome do produto; único por lojista |
| `preco_inicial_centavos` | integer | Preço no cadastro, em centavos (`> 0`) |
| `custo_inicial_centavos` | integer | Custo no cadastro, em centavos (`>= 0`) |
| `codigo_subitem_ipca` | text (FK `classificacao`) | O de-para para o subitem do IPCA — é essa FK que responde as perguntas de reajuste |
| `criado_em` | timestamptz | Data de cadastro |

Único por `(id_lojista, nome)`. Índice em `codigo_subitem_ipca` (`produto_subitem_idx`).

### reajuste

Um evento de mudança de preço, com o IPCA que o justificou. Insert-only: o preço corrente nunca é sobrescrito, é sempre derivado do último reajuste.

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | bigint (PK) | Chave substituta |
| `id_produto` | bigint (FK `produto`) | Produto reajustado |
| `preco_anterior_centavos` | integer | Preço antes do reajuste (`> 0`) |
| `preco_novo_centavos` | integer | Preço depois do reajuste (`> 0`, diferente do anterior) |
| `ipca_acumulado_ref` | numeric(8,4) | IPCA acumulado que justificou o reajuste |
| `mes_referencia_ipca` | date | Mês do IPCA usado como referência |
| `motivo` | text | Justificativa do reajuste |
| `aplicado_em` | timestamptz | Quando o reajuste foi aplicado |

Índice em `(id_produto, aplicado_em desc)` (`reajuste_produto_idx`).

### reajuste_custo

Um evento de mudança de custo (migration `0004`). Separado de `reajuste` porque o custo muda sem o preço mudar. Insert-only.

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | bigint (PK) | Chave substituta |
| `id_produto` | bigint (FK `produto`) | Produto |
| `custo_anterior_centavos` | integer | Custo antes (`>= 0`) |
| `custo_novo_centavos` | integer | Custo depois (`>= 0`, diferente do anterior) |
| `motivo` | text | Justificativa |
| `aplicado_em` | timestamptz | Quando passou a valer. Pode ser passado (lançamento atrasado) |

### venda_mensal

O que o produto vendeu em um mês (migration `0004`). Insert-only: corrigir é inserir outra linha para o mesmo mês, e vale a de `registrado_em` mais recente.

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | bigint (PK) | Chave substituta |
| `id_produto` | bigint (FK `produto`) | Produto |
| `mes_referencia` | date | Sempre o dia 1 do mês |
| `quantidade` | numeric(14,3) | Quantidade vendida (`>= 0`) |
| `receita_centavos` | bigint | Receita do mês, em centavos (`>= 0`) |
| `registrado_em` | timestamptz | Quando o lojista informou |

!!! info "Insert-only garantido pelo banco"
    Um gatilho recusa `UPDATE` em `reajuste`, `reajuste_custo`, `venda_mensal` e `observacao`. `DELETE` continua possível: apagar o lojista (LGPD) leva o histórico dele em cascata.

### produto_preco_atual (view)

Resolve o preço vigente de um produto sem duplicar dado: pega o último reajuste, ou o preço de cadastro se ainda não houve nenhum.

```sql
select p.id           as id_produto,
       p.id_lojista,
       p.nome,
       p.codigo_subitem_ipca,
       coalesce(r.preco_novo_centavos, p.preco_inicial_centavos) as preco_centavos,
       coalesce(r.aplicado_em, p.criado_em)                      as vigente_desde
from produto p
left join lateral (
    select preco_novo_centavos, aplicado_em
    from reajuste
    where id_produto = p.id
    order by aplicado_em desc
    limit 1
) r on true;
```

## Exemplos de Uso

```sql
-- Pergunta 5: reajuste mínimo para não perder margem em relação ao IPCA do último ano.
-- Junta o produto do lojista com a observação do IPCA pelo subitem.
select pr.nome, pr.preco_centavos, o.valor as ipca_acumulado_12m
from produto_preco_atual pr
join produto p on p.id = pr.id_produto
join observacao o
  on o.codigo_classificacao = p.codigo_subitem_ipca
 and o.codigo_localidade = (select codigo_localidade from lojista where id = p.id_lojista)
 and o.codigo_variavel = 2265
where pr.id_lojista = 1
order by o.mes_referencia desc
limit 1;

-- Aplicar um reajuste (dentro de uma transação: INSERT + leitura consistente do preço).
begin;
insert into reajuste (id_produto, preco_anterior_centavos, preco_novo_centavos,
                       ipca_acumulado_ref, mes_referencia_ipca, motivo)
values (1, 1000, 1080, 8.00, date '2026-07-01', 'reajuste anual pelo IPCA acumulado');
commit;
```

## Bronze: mudanças capturadas por CDC

`data/parquet/transacional/mudanca/`, espelhada em `bronze.transacional_mudanca`. Uma linha por mudança em `public`, na ordem do WAL. Decisão no [ADR de ingestão](../adr/cdc-vs-lote.md).

| Campo | Tipo | Descrição |
|---|---|---|
| `lsn` | bigint | Posição da mudança no WAL. Ordena os eventos como aconteceram |
| `lsn_commit` | bigint | Posição do commit da transação |
| `id_transacao` | bigint | Transação no Postgres; 0 na foto inicial |
| `tabela` | string | `lojista`, `produto`, `reajuste`, `reajuste_custo` ou `venda_mensal` |
| `operacao` | string | `r` (foto inicial), `I`, `U`, `D` ou `T` |
| `id_registro` | bigint, nulo | Coluna `id` da linha; nulo em `T` |
| `antes` | string (JSON), nulo | A linha antes da mudança, em `U` e `D` |
| `depois` | string (JSON), nulo | A linha depois da mudança, em `r`, `I` e `U` |
| `commit_em` | timestamp (UTC) | Hora do commit: tempo do sistema, não do negócio |
| `_id_resposta`, `_fonte`, `_requisicao`, `_ingerido_em` | | As colunas de rastreabilidade de toda tabela extraída |

!!! warning "O que nunca chega à Bronze"
    `cnpj` e `nome_fantasia`. Em `lojista`, passa só uma lista explícita de colunas, e o CNPJ vira `hash_estabelecimento`, um HMAC-SHA256 com chave. É pseudonimização, não anonimização: quem tem a chave consegue confirmar um CNPJ.

## Silver e Gold

| Modelo | Camada | Uma linha representa |
|---|---|---|
| `silver.stg_transacional__mudanca` | Staging | Uma mudança capturada |
| `silver.int_transacional__precos` | Intermediate | Evento de um produto, com o estado completo depois dele, na ordem do negócio |
| `silver.int_transacional__mensal` | Intermediate | Produto x mês, com o preço e o custo vigentes no fim do mês |
| `gold.dim_produto_preco_scd2` | Gold (SCD2) | Período em que preço, custo, nome e subitem de um produto ficaram iguais |
| `gold.fct_reajuste_lojista` | Gold | Um produto do lojista em um mês, comparado com o IPCA do subitem na praça dele |

Como ler a defasagem em `fct_reajuste_lojista`: positiva, o preço ficou atrás da inflação; negativa, reajustou acima dela. `reajuste_minimo_pct` é o reajuste que recupera a defasagem, e zero se não há o que recuperar. Exemplo calculado na [Evidência E3](../evidencias/e3/ipca_lojista.md#fato-lojista).

## Referências

- Esquema: `migrations/0002_lojista.sql` e `migrations/0004_evolucao_oltp_cdc_e_consultas.sql`
- Fonte de referência: [SIDRA/IBGE — Dicionário de Dados](sidra.md)
