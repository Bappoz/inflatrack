# PIB da China (World Bank)

Este documento registra as características arquiteturais e de negócio para a fonte de dados do **PIB da China**, obtida a partir da API REST pública do Banco Mundial (*World Bank API*).

## Séries coletadas

Todas as séries são obtidas diretamente da API do Banco Mundial (`api.worldbank.org`):

| Indicador | Código da Série | Unidade | Frequência de acesso |
|---|---|---|---|
| [Crescimento do PIB Real](https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG?locations=CN) | `NY.GDP.MKTP.KD.ZG` | Variação percentual anual (%) | Anual |
| [PIB Nominal em USD](https://data.worldbank.org/indicator/NY.GDP.MKTP.CD?locations=CN) | `NY.GDP.MKTP.CD` | Dólares americanos (USD) | Anual |

---

## 1. Fonte de Origem

| Atributo | Resposta |
| :--- | :--- |
| **Nome da fonte** | World Bank API – Indicadores Macroeconômicos da China |
| **Tipo** *(usuário / sistema / interna / terceiro)* | Terceiro |
| **Quem ou o que gera** | Banco Mundial / Departamento Nacional de Estatística da China (NBS) |
| **O que essa fonte contém** | Série histórica da taxa de crescimento do PIB da China e valor total produzido em USD, utilizada como indicador antecedente de demanda por commodities globais. |
| **Formato em que chega** *(JSON, CSV, formulário, API...)* | JSON (via API REST sem necessidade de chave de autenticação) |
| **Volume estimado** *(por dia ou por mês)* | 2 requisições por execução, uma por indicador. Payload extremamente leve; o histórico completo possui cerca de 60 pontos anuais por série. |
| **Frequência de chegada** *(tempo real / horária / diária / eventual)* | Anual, após a consolidação dos dados de cada período. |
| **Vazão** *(alta / média / baixa)* | Baixa |
| **Pureza** *(alta / média / baixa)* | Alta (dado oficial consolidado por organismo internacional multilateral) |
| **Previsibilidade do formato** *(alta / média / baixa)* | Alta (Schema JSON padronizado e mantido publicamente pelo Banco Mundial) |
| **Contém dado pessoal?** *(sim / não)* | Não |
| **Base legal LGPD** *(se contém dado pessoal)* | Não se aplica |
| **Retenção** *(por quanto tempo guardar)* | Permanente (histórico necessário para treinamento e análise causal em modelos preditivos de preços de commodities e repasse inflacionário) |
| **O que quebra se essa fonte falhar** | A atualização das features macroeconômicas externas. Os modelos de previsão continuam funcionando com o último valor histórico conhecido, sem afetar a integridade relacional do banco de dados. |

---

## 2. Conjunto de Dados / Armazenamento

| Atributo | Resposta |
| :--- | :--- |
| **Conjunto de dados** | Indicadores Macroeconômicos Externos – PIB da China |
| **Fonte de origem** *(nº da aba 1)* | World Bank API |
| **Formato atual** | `.json.gz` (raw), `.parquet` e tabela `pib_china` no DuckDB analítico compartilhado |
| **Texto ou binário** | Binário |
| **Orientação** *(linha / coluna / não se aplica)* | Linha, uma observação por ano |
| **Tamanho estimado** *(em 1 ano)* | < 1 MB / ano (série temporal extremamente leve) |
| **Como é lido** *(registro inteiro / poucas colunas / busca por chave)* | Busca pela chave temporal `ano` |
| **Frequência de leitura** | Média (acessado durante treinamento dos modelos analíticos de commodities e geração de relatórios) |
| **Formato proposto** | Manter o JSON gzip na camada raw, Parquet na camada transformada e DuckDB na camada servida. |
| **Justificativa da escolha** | O DuckDB único segue o [ADR 0002](../adr/0002-duckdb-unico.md) e permite junções temporais diretas com `commodity_cotacao`, conectando o crescimento chinês aos preços de commodities. |
| **Ganho esperado** *(se houver troca)* | Zero custo adicional de infraestrutura e latência imperceptível em consultas OLAP. |

Detalhamento campo a campo das tabelas: [Dicionário de Dados — PIB da China](../dicionario/pib_china.md).

---

## 3. Carga de trabalho

### Taxa de escrita

- **Carga histórica:** Evento único, 2 requisições HTTP, reexecutável. Cada indicador devolve todo o histórico em uma única chamada.
- **Regime:** 1 registro novo por ano, com possíveis revisões de anos anteriores.
- **Escrita transacional:** Nenhuma. A carga é realizada em lote (batch) e idempotente.

### Taxa de leitura e padrão de acesso

| # | Consulta | Frequência | Tipo | Latência Alvo | Acesso |
|---|---|---|---|---|---|
| 1 | Coleta na API do Banco Mundial | 1 rodada/ano | lote | < 5 s | `api.worldbank.org/v2/country/CHN/indicator/...` |
| 2 | Cruzamento temporal PIB China x Preço de Commodities | Média (sob demanda) | agregada | < 300 ms | `JOIN pib_china p ON year(c.data_referencia) = p.ano` |

---

## 4. Restrições que a origem impõe

- **Frequência de atualização lenta:** Como os indicadores são anuais, consultas diárias ou trimestrais à API normalmente não trazem novos registros.
- **Defasagem de publicação:** O PIB consolidado é divulgado com meses de atraso após o fechamento do ano, exigindo que os modelos considerem a defasagem temporal (*lag*).
- **Sem autenticação exigida:** A API pública do Banco Mundial não exige chave de API (API Key), porém recomenda-se respeitar boas práticas de concorrência nas requisições.
