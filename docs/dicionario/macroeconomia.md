# Dicionário de Dados - Macroeconomia

Esta seção detalha o schema físico armazenado no banco analítico colunar (**DuckDB**). Diferente da modelagem relacional transacional (que fragmenta os dados em múltiplas tabelas normalizadas), a modelagem colunar mantém tabelas largas e contínuas otimizadas para leitura rápida de milhares de dias de Séries Temporais.

## 1. Banco de Dados Analítico (`inflatrack.duckdb`)

### Tabela: `dolar_cotacao`
Armazena a cotação oficial diária (fechamento) do Dólar Comercial americano.

| Coluna | Tipo (DuckDB) | Chave | Descrição |
| :--- | :--- | :--- | :--- |
| `data_referencia` | `DATE` | PK | Data de referência da cotação. Feriados e finais de semana herdam a última cotação útil de sexta-feira. |
| `cotacaoCompra` | `DOUBLE` | | Preço pago pelo banco na compra de dólares (irrelevante para a ponta importadora). |
| `cotacaoVenda` | `DOUBLE` | | Preço cobrado pelo banco na venda de dólares. **Variável chave para cálculo de repasse de inflação de matérias-primas importadas**. |

### Tabela: `selic_taxa`
Armazena a Taxa Básica de Juros (Efetiva) diária apurada pelo Banco Central.

| Coluna | Tipo (DuckDB) | Chave | Descrição |
| :--- | :--- | :--- | :--- |
| `data_referencia` | `DATE` | PK | Data de referência da taxa. Finais de semana herdam o último valor útil divulgado pelo BCB. |
| `taxa_efetiva` | `DOUBLE` | | Taxa Selic anualizada efetiva daquele dia, em formato percentual puro (ex: `10.5` representa 10,5% a.a). |

### Tabela: `commodity_cotacao`
Armazena o fechamento de commodities globais, extraídas da AlphaVantage.

| Coluna | Tipo (DuckDB) | Chave | Descrição |
| :--- | :--- | :--- | :--- |
| `symbol` | `VARCHAR` | PK | Código internacional do ativo financeiro (ex: `WTI` para Petróleo, `COFFEE` para café). |
| `data_referencia` | `DATE` | PK | Data de referência (fechamento comercial) da cotação do ativo. |
| `preco` | `DOUBLE` | | Preço internacional da commodity na data referida (a unidade monetária e de peso varia conforme o símbolo). |
