# Como rodar a Ingestão de Commodities e Energia

Este guia descreve os passos necessários para executar o pipeline de extração de dados da API Alpha Vantage (commodities agrícolas e energia) e sua carga no banco de dados analítico local (DuckDB).

## 1. Pré-requisitos (Variáveis de Ambiente)

Antes de rodar os scripts, é obrigatório possuir uma chave da API da Alpha Vantage. 
Abra o arquivo `.env` na raiz do projeto e adicione/preencha a sua chave na variável correspondente:

```env
ALPHAVANTAGE_API_KEY=sua_chave_aqui
```

> **Nota:** O plano gratuito da API possui um limite de 25 requisições por dia. O pipeline já está configurado para respeitar automaticamente a taxa de requisições permitidas por minuto (~13s entre cada requisição).

## 2. Bronze em Delta (coleta)

`src/inflatrack/bronze/commodities.py` consulta a API pelo cliente `src/inflatrack/clients/alphavantage.py`, checa a resposta (cota esgotada, série vazia, volume mínimo) e grava duas tabelas Delta em `data/parquet/commodities/`:

* `resposta/`: a resposta original, deduplicada pelo hash SHA-256;
* `cotacao/`: uma linha por data, particionada por `symbol`. A partição do símbolo é substituída quando a série muda.

Desde a E3 não há mais `data/raw/commodities_raw/` nem Parquet por commodity na raiz de `data/parquet/`.

Todas as commodities (9 requisições da cota diária):

```bash
just bronze-commodities
# ou: uv run python -m inflatrack.bronze.commodities --commodity ALL
```

Uma só (ex.: Petróleo Brent):

```bash
uv run python -m inflatrack.bronze.commodities --commodity BRENT
```

*Os símbolos disponíveis são:* `WTI`, `BRENT`, `NATURAL_GAS`, `WHEAT`, `CORN`, `COTTON`, `SUGAR`, `COFFEE`, e `ALL_COMMODITIES` (índice global).

Checagem da Bronze gravada (símbolos, volume e datas repetidas), sem requisição:

```bash
just bronze-commodities-checar
```

## 3. Carga no DuckDB (`bronze.commodities_cotacao`)

`src/inflatrack/loaders/load_commodities.py` espelha o Delta em `bronze.commodities_cotacao`, criando a tabela com o esquema do próprio Delta (`common.bronze.carregar_duckdb`). Rodar duas vezes não duplica linhas.

```bash
uv run python -m inflatrack.loaders.load_commodities
```

## 4. Silver no dbt

`silver.stg_commodities__cotacao` limpa a série e `silver.int_commodities__mensal` resume cada commodity no grão mensal (`mes_referencia` no dia 1):

```bash
uv run dbt build --select +int_commodities__mensal
```
