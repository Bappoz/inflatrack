# Como rodar a Ingestão de Commodities e Energia

Este guia descreve os passos necessários para executar o pipeline de extração de dados da API Alpha Vantage (commodities agrícolas e energia) e sua carga no banco de dados analítico local (DuckDB).

## 1. Pré-requisitos (Variáveis de Ambiente)

Antes de rodar os scripts, é obrigatório possuir uma chave da API da Alpha Vantage. 
Abra o arquivo `.env` na raiz do projeto e adicione/preencha a sua chave na variável correspondente:

```env
ALPHAVANTAGE_API_KEY=sua_chave_aqui
```

> **Nota:** O plano gratuito da API possui um limite de 25 requisições por dia. O pipeline já está configurado para respeitar automaticamente a taxa de requisições permitidas por minuto (~13s entre cada requisição).

## 2. Inicialização do Banco de Dados

O primeiro passo é garantir que o arquivo do DuckDB (`data/duckdb/inflatrack.duckdb`), as suas tabelas base e suas visualizações (views) existam. 
Para inicializar o banco pela primeira vez (ou recriar suas estruturas), execute a partir da raiz do projeto:

```bash
uv run python scripts/init_db.py
```

Isso criará as tabelas `commodity` (dimensão), `commodity_cotacao` (fatos) e a view em formato colunar `vw_commodities_features`.

## 3. Ingestão dos Dados (Raw / Parquet)

O script de ingestão consulta a API, grava a resposta crua em `data/raw/commodities_raw/` (JSON gzip) e só depois transforma esse arquivo cru em `.parquet` dentro de `data/parquet/`.

Para baixar o histórico de **todas** as commodities configuradas (este comando consumirá 9 requisições da sua cota diária):
```bash
uv run python -m inflatrack.ingest_commodities --commodity ALL --modo historico
```

Se desejar realizar a ingestão de uma **commodity específica** (ex: Petróleo Brent):
```bash
uv run python -m inflatrack.ingest_commodities --commodity BRENT --modo historico
```

*Os símbolos disponíveis são:* `WTI`, `BRENT`, `NATURAL_GAS`, `WHEAT`, `CORN`, `COTTON`, `SUGAR`, `COFFEE`, e `ALL_COMMODITIES` (índice global).

## 4. Carga para o Banco (DuckDB)

Após extrair os dados e salvá-los no formato `.parquet`, é necessário carregá-los para as tabelas do banco DuckDB. 
O script de carga processa automaticamente todos os parquets existentes em `data/parquet/` e realiza a atualização e inserção (*UPSERT*) nos dados finais:

```bash
uv run python -m inflatrack.load_commodities
```

## 5. Validação dos Dados

Com os dados carregados, eles já estarão disponíveis, transpostos e estruturados como colunas, prontos para uso em Machine Learning pelo formato *Wide*.
Caso deseje testar a visualização dos dados via Python, você pode rodar o seguinte teste:

```python
import duckdb
conn = duckdb.connect("data/duckdb/inflatrack.duckdb")
df = conn.execute("SELECT * FROM vw_commodities_features ORDER BY data_referencia DESC LIMIT 5").df()
print(df)
```
