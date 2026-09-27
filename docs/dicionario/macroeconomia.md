# Dicionário de Dados - Macroeconomia

Esta seção detalha o schema físico armazenado no banco analítico colunar (**DuckDB**). Diferente da modelagem relacional transacional (que fragmenta os dados em múltiplas tabelas normalizadas), a modelagem colunar mantém tabelas largas e contínuas otimizadas para leitura rápida de milhares de dias de Séries Temporais.

## 1. Banco de Dados Analítico (`inflatrack.duckdb`)

### Tabela: `dolar_cotacao`
Armazena a cotação oficial diária (fechamento) do Dólar Comercial americano.

| Coluna | Tipo (DuckDB) | Chave | Descrição |
| :--- | :--- | :--- | :--- |
| `data_referencia` | `DATE` | PK | Data de referência. Feriados e fins de semana recebem a última cotação útil conhecida. |
| `cotacao_compra` | `DOUBLE` | | Preço pago pelo banco na compra de dólares. |
| `cotacao_venda` | `DOUBLE` | | Preço cobrado pelo banco na venda de dólares. |
| `observado` | `BOOLEAN` | | `true` quando a cotação foi publicada para a data; `false` quando foi preenchida. |

### Tabela: `selic_taxa`
Armazena a Taxa Básica de Juros (Efetiva) diária apurada pelo Banco Central.

| Coluna | Tipo (DuckDB) | Chave | Descrição |
| :--- | :--- | :--- | :--- |
| `data_referencia` | `DATE` | PK | Data de referência. Feriados e fins de semana recebem o último valor útil conhecido. |
| `taxa_dia_pct` | `DOUBLE` | | Taxa Selic efetiva diária da série SGS 11, em percentual ao dia. |
| `observado` | `BOOLEAN` | | `true` quando a taxa foi publicada para a data; `false` quando foi preenchida. |

### Tabela: `commodity_cotacao`
Armazena o fechamento de commodities globais, extraídas da AlphaVantage.

| Coluna | Tipo (DuckDB) | Chave | Descrição |
| :--- | :--- | :--- | :--- |
| `symbol` | `VARCHAR` | PK | Código internacional do ativo financeiro (ex: `WTI` para Petróleo, `COFFEE` para café). |
| `data_referencia` | `DATE` | PK | Data de referência (fechamento comercial) da cotação do ativo. |
| `preco` | `DOUBLE` | | Preço internacional da commodity na data referida (a unidade monetária e de peso varia conforme o símbolo). |
