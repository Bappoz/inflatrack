# Salário Mínimo e Cesta Básica (DIEESE) — Dicionário de Dados

## Contexto

Esta seção detalha o schema físico da fonte de dados da Pesquisa Nacional da Cesta Básica de Alimentos (DIEESE), armazenado na tabela `salario_minimo` dentro do banco analítico compartilhado (**DuckDB** em `data/duckdb/inflatrack.duckdb`), conforme estabelecido pelo [ADR 0002](../adr/0002-duckdb-unico.md).

A fonte fornece a série histórica mensal do salário mínimo oficial federal (nominal) e do salário mínimo necessário calculado com base no preceito constitucional (CF/88, art. 7º, IV) e no custo de vida apurado nas capitais.

No estado atual, os dados coletados são os salários nominal e necessário. Não há uma série
independente de custo da cesta básica no Delta; portanto, ela não pode ser apresentada como medida
observada até que a equipe incorpore uma fonte e tabela próprias.

---

## Modelo Conceitual

A tabela `salario_minimo` atua como dimensão temporal de poder de compra e renda familiar, vinculando-se temporalmente por `ano_mes` às observações de preços de produtos e índices inflacionários:

<div class="diagrama">
--8<-- "docs/assets/diagramas/esquema-salario-minimo.svg"
</div>

---

## Entidades

### Tabela: `salario_minimo`

Armazena os valores mensais de salário mínimo desde o início do Plano Real (julho de 1994).

| Coluna | Tipo (DuckDB) | Chave | Descrição |
|---|---|---|---|
| `ano_mes` | `VARCHAR(7)` | PK | Ano e mês de apuração no formato `YYYY-MM` (ex.: `2026-08`). |
| `data_referencia` | `DATE` | | Data canônica referente ao primeiro dia do mês (`YYYY-MM-01`). Facilita junções com séries temporais contínuas. |
| `ano` | `SMALLINT` | | Ano civil da observação (ex.: `2026`), útil para agregações anuais sem custo de parsing. |
| `mes` | `TINYINT` | | Mês civil da observação (1 a 12). |
| `salario_nominal` | `DOUBLE` | | Salário mínimo oficial federal vigente fixado por lei no mês de referência (em R$). |
| `salario_necessario` | `DOUBLE` | | Salário mínimo calculado pelo DIEESE necessário para suprir as despesas básicas de uma família de quatro pessoas (em R$). |
| `multiplo_necessario_nominal` | `DOUBLE` | | Múltiplo derivado pela razão entre o salário necessário e o nominal (`salario_necessario / salario_nominal`). |

---

## Consultas de Exemplo

### 1. Série Recente do Poder de Compra

```sql
SELECT 
    ano_mes,
    salario_nominal,
    salario_necessario,
    round(multiplo_necessario_nominal, 2) AS vezes_nominal
FROM salario_minimo
WHERE ano >= 2024
ORDER BY data_referencia DESC;
```

### 2. Variação Interanual do Salário Nominal vs. Inflação

Permite avaliar se o piso salarial acompanhou o ritmo inflacionário no período de 12 meses:

```sql
SELECT 
    ano_mes,
    salario_nominal,
    round((salario_nominal / lag(salario_nominal, 12) OVER (ORDER BY data_referencia) - 1) * 100, 2) AS reajuste_anual_salario_pct
FROM salario_minimo
ORDER BY data_referencia DESC;
```

---

## Bronze em Delta

As duas tabelas gravadas pelo ingestor em `data/parquet/salario_minimo/`, em formato Delta. Ficam no Delta e substituem a camada Raw em `.html.gz`. Quando necessário, o DuckDB lê com `delta_scan`.

### salario_minimo_resposta

Armazena o HTML original integral recebido do DIEESE. Uma linha por resposta **diferente** (deduplicada por `hash_corpo`).

| Campo | Tipo | Descrição |
|---|---|---|
| `id_resposta` | string | Identificador da resposta: o hash SHA-256 do corpo |
| `_fonte` | string | Sempre `"salario_minimo"` |
| `_requisicao` | string | URL consultada no portal do DIEESE |
| `_ingerido_em` | timestamp (UTC) | Momento do download |
| `status_http` | smallint, nulo | Status HTTP da resposta (200, ou nulo se importado do Raw) |
| `tipo_conteudo` | string, nulo | `Content-Type` retornado pelo servidor |
| `corpo` | string | O documento HTML na íntegra |
| `hash_corpo` | string | SHA-256 do corpo (idempotência) |
| `tamanho_bytes` | bigint | Tamanho do documento em bytes |

### salario_minimo_mes

Série temporal extraída com **todas as linhas** da tabela HTML, tipada e sem descarte. Não inclui colunas calculadas (o múltiplo necessário/nominal é delegado para o dbt).

| Campo | Tipo | Descrição |
|---|---|---|
| `ano_mes` | string | Identificador mensal no formato `YYYY-MM` (ex.: `2026-08`) |
| `data_referencia` | date | Primeiro dia do mês (`YYYY-MM-01`), chave canônica de junção |
| `ano` | smallint | Ano civil da observação |
| `mes` | smallint | Mês civil da observação (1 a 12) |
| `salario_nominal` | decimal(12,2) | Salário mínimo oficial federal vigente (em R$) |
| `salario_necessario` | decimal(12,2) | Salário mínimo necessário apurado pelo DIEESE (em R$) |
| `_id_resposta` | string | Chave estrangeira para `salario_minimo_resposta.id_resposta` |
| `_fonte` | string | Sempre `"salario_minimo"` |
| `_requisicao` | string | URL que originou a observação |
| `_ingerido_em` | timestamp (UTC) | Carimbo temporal da ingestão |

**Granularidade:** uma linha por mês apurado × `salario_nominal` × `salario_necessario`. Caso o DIEESE retifique um mês já divulgado, a alteração entra como **linha nova**, assegurando linhagem e histórico imutável (*insert-only*).

O modelo `silver.int_salario_minimo__mensal` consolida a última revisão de cada mês, calcula a razão
entre salário necessário e nominal, as variações e a média móvel nominal de três meses. A série
disponível desde 1994 cobre o recorte a partir de 2006 sem truncamento.

