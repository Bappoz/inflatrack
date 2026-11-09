# Ingestão de Commodities e Energia via Alpha Vantage

Script para puxar séries históricas de preços globais de commodities agrícolas e de energia (petróleo e gás) da API Alpha Vantage. Os dados irão para a camada bronze (raw) no formato colunar **Apache Parquet**, prontos para integração com Airflow, e depois transformados e carregados localmente no **DuckDB**.

## User Review Required

> [!IMPORTANT]
> **API Key**: O script vai ler a chave de `ALPHAVANTAGE_API_KEY` do `.env`. Já adicionei o campo lá para você preencher. O plano free tem limite de **25 requests/dia** e **5 requests/min**. O script inclui rate limiting para respeitar a restrição de RPM.
> 
> 

## Análise e Definição da Tabela (DuckDB & Parquet)

Para algoritmos de Machine Learning, o formato esperado é o **colunar (Wide Format)**, onde cada commodity é uma *feature* (coluna) e cada linha é uma data.

Na **Engenharia de Dados**, o padrão para armazenar séries temporais de múltiplos ativos é o **formato de linhas (Tall Format)**, pela flexibilidade de adicionar novos ativos sem alterar schemas. Com o DuckDB, conseguimos o melhor dos dois mundos de forma nativa e embarcada:

1. **Armazenamento (DuckDB - Tall Format):**
Tabelas `commodity` e `commodity_cotacao` dentro de um arquivo de banco local (ex: `data/inflatrack.duckdb`).
*Por que?* Se amanhã houver a necessidade de adicionar "Ouro", não é necessário alterar o schema. As assimetrias de calendário de feriados entre ativos são tratadas naturalmente.
2. **Consumo para Machine Learning (Pivot Nativo - Wide Format):**
O DuckDB suporta transposição de linhas para colunas nativamente. Criaremos uma **View** (ou uma query direta no pipeline de Python) que usa a cláusula `PIVOT`. Quando o modelo for consumir, o DuckDB processa em milissegundos e entrega diretamente para um DataFrame do Pandas:

```
CREATE VIEW vw_commodities_features AS 
PIVOT commodity_cotacao 
ON symbol 
USING avg(preco);

```

O banco já entregará a tabela assim, pronta para o `fit()`:

| data\_referencia | BRENT | WTI | WHEAT | CORN |
| --- | --- | --- | --- | --- |
| 2026-09-21 | 74.50 | 70.10 | 220.00 | 180.00 |

## Sugestão de Frequência de Requests

* **Quantas requisições?** Temos 9 indicadores mapeados. A carga full fará 9 requests.
* **Frequência sugerida:** **1 vez por dia**.
* **Justificativa:** Como o limite do plano free é 25/dia e os fechamentos de commodities na Alpha Vantage são diários, semanais ou mensais, rodar o script diariamente consome apenas 9 requests diários. Sobram 16 requests de margem.

## Proposed Changes

### 1. Escopo de Indicadores

| Categoria | Commodity | `function` | Unidade |
| --- | --- | --- | --- |
| Energia | Petróleo WTI | `WTI` | USD/barrel |
| Energia | Petróleo Brent | `BRENT` | USD/barrel |
| Energia | Gás Natural | `NATURAL_GAS` | USD/MMBtu |
| Agrícola | Trigo (Wheat) | `WHEAT` | USD/metric ton |
| Agrícola | Milho (Corn) | `CORN` | USD/metric ton |
| Agrícola | Algodão (Cotton) | `COTTON` | USD/metric ton |
| Agrícola | Açúcar (Sugar) | `SUGAR` | cents/pound |
| Agrícola | Café (Coffee) | `COFFEE` | cents/pound |
| Geral | Índice Global | `ALL_COMMODITIES` | index (2016=100) |

### 2. Banco de Dados Local (DuckDB)

#### [NEW] `scripts/setup_duckdb.sql`

* Script SQL leve para inicializar o arquivo `data/inflatrack.duckdb`.
* Criação das tabelas `commodity` e `commodity_cotacao`.
* Criação da **View** `vw_commodities_features` utilizando o operador `PIVOT` do DuckDB.

### 3. Cliente Alpha Vantage e Ingestão Raw (Parquet)

#### [NEW] `alphavantage.py`

* Classe com os 9 endpoints.
* Função `buscar_commodity(...)` com rate limiting (12s entre requisições).

#### [NEW] `ingest_commodities.py`

* CLI com modos histórico e incremental.
* Converte a resposta JSON em um *DataFrame* local (via Pandas/Polars) e salva na camada bronze como **Apache Parquet** (`.parquet`).

### 4. Transformação (Silver/Gold no DuckDB)

#### [NEW] `load_commodities.py`

* Script que conecta ao arquivo `data/inflatrack.duckdb`.
* Utiliza a leitura nativa do DuckDB para processar os arquivos `.parquet` diretamente do disco.
* Executa a inserção (`UPSERT`) nas tabelas `commodity` e `commodity_cotacao`.

## Verification Plan

### Manual Verification

1. Rodar `uv run python -m inflatrack.ingest_commodities --commodity BRENT --modo historico`.
2. Validar se o arquivo `brent_historico.parquet` foi salvo corretamente em `data/commodities_raw`.
3. Rodar a inicialização do banco (`scripts/setup_duckdb.sql` executado via CLI do DuckDB ou script Python).
4. Executar o script de carga no banco (`load_commodities.py`).
5. **Verificar o output colunar**: Conectar ao arquivo `.duckdb` localmente (via Python ou DBeaver) e rodar um `SELECT * FROM vw_commodities_features LIMIT 10`, checando se o PIVOT transformou as linhas em colunas (features) corretamente e em formato legível pelo Pandas.

---

