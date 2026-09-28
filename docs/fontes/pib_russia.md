# PIB da Rússia (World Bank)

Este documento registra as características arquiteturais e de negócio para a fonte de dados do **PIB da Rússia**, obtida a partir da API REST pública do Banco Mundial (*World Bank API*).

## Séries coletadas

Todas as séries são obtidas diretamente da API do Banco Mundial (`api.worldbank.org`):

| Indicador | Código da Série | Unidade | Frequência de acesso |
|---|---|---|---|
| [Crescimento do PIB Real](https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG?locations=RU) | `NY.GDP.MKTP.KD.ZG` | Variação percentual anual (%) | Anual |
| [PIB Nominal em USD](https://data.worldbank.org/indicator/NY.GDP.MKTP.CD?locations=RU) | `NY.GDP.MKTP.CD` | Dólares americanos (USD) | Anual |

---

## 1. Fonte de Origem

| Atributo | Resposta |
| :--- | :--- |
| **Nome da fonte** | World Bank API – Indicadores Macroeconômicos da Rússia |
| **Tipo** *(usuário / sistema / interna / terceiro)* | Terceiro |
| **Quem ou o que gera** | Banco Mundial / Serviço Federal de Estatísticas do Estado da Rússia (Rosstat) |
| **O que essa fonte contém** | Série histórica da taxa de crescimento do PIB da Rússia e valor total produzido em USD, utilizada como variável explicativa de choques geopolíticos na oferta de energia (petróleo e gás) e commodities agrícolas/fertilizantes. |
| **Formato em que chega** *(JSON, CSV, formulário, API...)* | JSON (via API REST sem necessidade de chave de autenticação) |
| **Volume estimado** *(por dia ou por mês)* | 2 requisições por execução (uma por indicador). Histórico leve de ~30 a 60 pontos anuais por série. |
| **Frequência de chegada** *(tempo real / horária / diária / eventual)* | Anual, após consolidação oficial. |
| **Vazão** *(alta / média / baixa)* | Baixa |
| **Pureza** *(alta / média / baixa)* | Alta (dado oficial consolidado por organismo internacional multilateral) |
| **Previsibilidade do formato** *(alta / média / baixa)* | Alta (Schema JSON padronizado e mantido publicamente pelo Banco Mundial) |
| **Contém dado pessoal?** *(sim / não)* | Não |
| **Base legal LGPD** *(se contém dado pessoal)* | Não se aplica |
| **Retenção** *(por quanto tempo guardar)* | Permanente (necessário para treinamento e análise causal em modelos preditivos de choques de oferta em commodities) |
| **O que quebra se essa fonte falhar** | A atualização das features macroeconômicas da Rússia no banco analítico. Os modelos seguem operando com a última observação conhecida sem comprometer o banco relacional. |

---

## 2. Conjunto de Dados / Armazenamento

| Atributo | Resposta |
| :--- | :--- |
| **Conjunto de dados** | Indicadores Macroeconômicos Externos – PIB da Rússia |
| **Fonte de origem** *(nº da aba 1)* | World Bank API |
| **Formato atual** | `.json.gz` (raw em `data/raw/pib_russia/`), `.parquet` (silver em `data/parquet/pib_russia/`) e tabela `pib_russia` no DuckDB analítico compartilhado |
| **Texto ou binário** | Binário (o raw comprimido em gzip, Parquet e DuckDB) |
| **Orientação** *(linha / coluna / não se aplica)* | Linha, uma observação por ano |
| **Tamanho estimado** *(em 1 ano)* | < 1 MB / ano (série temporal leve) |
| **Como é lido** *(registro inteiro / poucas colunas / busca por chave)* | Busca pela chave temporal `ano` |
| **Frequência de leitura** | Média (acessado durante treinamento dos modelos analíticos de commodities e fertilizantes) |
| **Formato proposto** | Manter o JSON gzip na camada raw, Parquet na camada transformada e DuckDB na camada servida. |
| **Justificativa da escolha** | O DuckDB único segue o [ADR 0002](../adr/0002-duckdb-unico.md) e permite junções temporais diretas com `commodity_cotacao`. |
| **Ganho esperado** *(se houver troca)* | Zero custo adicional de infraestrutura e latência imperceptível em consultas OLAP. |

Detalhamento campo a campo das tabelas: [Dicionário de Dados — PIB da Rússia](../dicionario/pib_russia.md).

---

## 3. Carga de trabalho

### Taxa de escrita

- **Carga histórica:** Evento único, 2 requisições HTTP, reexecutável.
- **Regime:** 1 registro novo por ano, com possíveis revisões de anos anteriores.
- **Escrita transacional:** Nenhuma. Carga em lote (batch) e idempotente.

### Taxa de leitura e padrão de acesso

| # | Consulta | Frequência | Tipo | Latência Alvo | Acesso |
|---|---|---|---|---|---|
| 1 | Coleta na API do Banco Mundial | 1 rodada/ano | lote | < 5 s | `api.worldbank.org/v2/country/RUS/indicator/...` |
| 2 | Cruzamento temporal PIB Rússia x Preço de Petróleo e Trigo | Média (sob demanda) | agregada | < 300 ms | `JOIN pib_russia r ON year(c.data_referencia) = r.ano` |

---

## 4. Restrições que a origem impõe

- **Frequência de atualização lenta:** Indicadores anuais divulgados com atraso de publicação pós-período.
- **Sem autenticação exigida:** API pública sem chave de API.
