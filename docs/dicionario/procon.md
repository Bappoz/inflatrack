# Cesta Básica do PROCON — Dicionário de Dados

## Contexto

Esta seção detalha o schema físico da fonte da **Cesta Básica do PROCON**, armazenada na tabela `bronze.procon_cesta_basica` dentro do banco analítico compartilhado (**DuckDB** em `data/duckdb/inflatrack.duckdb`), bem como suas visualizações na camada Silver do **dbt**.

---

## 1. Tabela Bronze: `bronze.procon_cesta_basica`

Armazena as observações de preços colhidas no varejo/atacado com os metadados de linhagem da camada Bronze.

| Coluna | Tipo | Chave | Descrição |
|---|---|---|---|
| `data_pesquisa` | `DATE` | Sim | Data canônica referente à apuração mensal da pesquisa (ex.: `2026-08-01`). |
| `produto` | `VARCHAR` | Sim | Nome padronizado do produto na cesta (ex.: `Arroz Agulhinha`, `Feijão Carioca`). |
| `unidade` | `VARCHAR` | | Unidade de comercialização (ex.: `5 kg`, `1 kg`, `900 ml`, `800 g`). |
| `preco_medio` | `DOUBLE` | Sim | Preço médio apurado para o produto na praça (em R$). |
| `preco_minimo` | `DOUBLE` | | Menor preço encontrado na pesquisa amostral (em R$). |
| `preco_maximo` | `DOUBLE` | | Maior preço encontrado na pesquisa amostral (em R$). |
| `praca` | `VARCHAR` | Sim | Cidade ou região da pesquisa de preços (ex.: `Brasília`, `São Paulo`). |
| `codigo_subitem_ipca` | `VARCHAR` | | Código correspondente do subitem na classificação oficial do IPCA (SIDRA). |
| `_id_resposta` | `VARCHAR` | | Hash SHA-256 da resposta/arquivo ingerido para rastreabilidade. |
| `_fonte` | `VARCHAR` | | Identificador da fonte (`procon`). |
| `_requisicao` | `VARCHAR` | | Caminho de origem ou URL da requisição de ingestão. |
| `_ingerido_em` | `TIMESTAMPTZ` | | Carimbo de data/hora UTC em que o dado foi incorporado à Bronze. |

---

## 2. Modelo dbt: `silver.int_procon__mensal`

Modelo intermediário que calcula a série de variações percentuais mês a mês e apoia o cruzamento com o IPCA.

| Coluna | Tipo | Descrição |
|---|---|---|
| `mes_referencia` | `DATE` | Primeiro dia do mês da pesquisa de preços. |
| `produto` | `VARCHAR` | Nome do produto pesquisado. |
| `unidade` | `VARCHAR` | Unidade física de medida. |
| `praca` | `VARCHAR` | Praça da apuração de preços. |
| `codigo_subitem_ipca` | `VARCHAR` | Código do subitem no IPCA para relacionamento com o SIDRA. |
| `preco_medio` | `DECIMAL(14,2)` | Preço médio apurado no mês corrente. |
| `preco_minimo` | `DECIMAL(14,2)` | Preço mínimo no mês corrente. |
| `preco_maximo` | `DECIMAL(14,2)` | Preço máximo no mês corrente. |
| `preco_medio_anterior` | `DECIMAL(14,2)` | Preço médio do produto no mês anterior (`lag`). |
| `variacao_mensal_preco_pct` | `DECIMAL(12,4)` | Variação percentual calculada em relação ao mês anterior. |

---

## 3. Tabela Fato Gold: `gold.fct_cesta_basica_mensal`

Fato central de mercado que consolida os preços médios, variações mensais e vínculos com as dimensões de tempo (`dim_calendario`) e localidade (`dim_localidade`), pronta para consumo por dashboards e consultas de gestão.

| Coluna | Tipo | Chave | Descrição |
|---|---|---|---|
| `mes_referencia` | `DATE` | FK | Primeiro dia do mês (`dim_calendario.mes_referencia`). |
| `ano` | `SMALLINT` | | Ano civil da apuração (`dim_calendario.ano`). |
| `mes` | `TINYINT` | | Mês civil da apuração (1 a 12). |
| `codigo_localidade` | `INTEGER` | FK | Código IBGE da localidade (`dim_localidade.codigo_localidade`). |
| `nome_praca` | `VARCHAR` | | Nome da praça/cidade pesquisada. |
| `produto_mercado` | `VARCHAR` | | Nome padronizado do produto na cesta. |
| `unidade` | `VARCHAR` | | Unidade de medida (ex.: `5 kg`, `1 l`). |
| `codigo_subitem_ipca` | `VARCHAR` | | Código correspondente do subitem no IPCA para junções com `fct_inflacao_mensal`. |
| `preco_medio_mercado` | `DECIMAL(14,2)` | | Preço médio apurado no varejo/atacado no mês. |
| `preco_minimo_mercado` | `DECIMAL(14,2)` | | Preço mínimo encontrado no mercado. |
| `preco_maximo_mercado` | `DECIMAL(14,2)` | | Preço máximo encontrado no mercado. |
| `preco_anterior_mercado` | `DECIMAL(14,2)` | | Preço médio de mercado do mês anterior. |
| `variacao_mensal_mercado_pct` | `DECIMAL(12,4)` | | Variação percentual do preço de mercado frente ao mês anterior. |

