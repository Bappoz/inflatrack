# PIB dos Estados Unidos (World Bank)

Este documento registra as características arquiteturais e de negócio para a fonte de dados do **PIB dos Estados Unidos**, obtida a partir da API REST pública do Banco Mundial (*World Bank API*).

## Séries coletadas

Todas as séries são obtidas diretamente da API do Banco Mundial (`api.worldbank.org`):

| Indicador | Código da Série | Unidade | Frequência de acesso |
|---|---|---|---|
| [Crescimento do PIB Real](https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG?locations=US) | `NY.GDP.MKTP.KD.ZG` | Variação percentual anual (%) | Anual |
| [PIB Nominal em USD](https://data.worldbank.org/indicator/NY.GDP.MKTP.CD?locations=US) | `NY.GDP.MKTP.CD` | Dólares americanos (USD) | Anual |

---

## 1. Fonte de Origem

| Atributo | Resposta |
| :--- | :--- |
| **Nome da fonte** | World Bank API – Indicadores Macroeconômicos dos Estados Unidos |
| **Tipo** *(usuário / sistema / interna / terceiro)* | Terceiro |
| **Quem ou o que gera** | Banco Mundial / U.S. Bureau of Economic Analysis (BEA) |
| **O que essa fonte contém** | Série histórica do crescimento real do PIB dos EUA e valor total produzido em USD, utilizada como barômetro da atividade econômica global, apetite por risco e indicador antecedente de demanda e repasse inflacionário internacional. |
| **Formato em que chega** *(JSON, CSV, formulário, API...)* | JSON (via API REST sem necessidade de chave de autenticação) |
| **Volume estimado** *(por dia ou por mês)* | 2 requisições por execução (uma por indicador). Histórico leve de ~60 a 65 pontos anuais por série. |
| **Frequência de chegada** *(tempo real / horária / diária / eventual)* | Anual, após consolidação dos dados oficiais do BEA pelo Banco Mundial. |
| **Vazão** *(alta / média / baixa)* | Baixa |
| **Pureza** *(alta / média / baixa)* | Alta (dado oficial consolidado por organismo internacional multilateral) |
| **Previsibilidade do formato** *(alta / média / baixa)* | Alta (Schema JSON padronizado e mantido publicamente pelo Banco Mundial) |
| **Contém dado pessoal?** *(sim / não)* | Não |
| **Base legal LGPD** *(se contém dado pessoal)* | Não se aplica |
| **Retenção** *(por quanto tempo guardar)* | Permanente (necessário para treinamento e análise causal em modelos preditivos de preços de commodities e taxas de câmbio) |
| **O que quebra se essa fonte falhar** | A atualização das features macroeconômicas dos EUA no banco analítico. Os modelos preditivos continuam operando com o último valor histórico conhecido sem afetar a integridade relacional. |

---

## 2. Conjunto de Dados / Armazenamento

| Atributo | Resposta |
| :--- | :--- |
| **Conjunto de dados** | Indicadores Macroeconômicos Externos – PIB dos EUA |
| **Fonte de origem** *(nº da aba 1)* | World Bank API |
| **Formato atual** | `.json.gz` (raw em `data/raw/pib_usa/`), `.parquet` (silver em `data/parquet/pib_usa/`) e tabela `pib_usa` no DuckDB analítico compartilhado |
| **Texto ou binário** | Binário (o raw comprimido em gzip, Parquet e DuckDB) |
| **Orientação** *(linha / coluna / não se aplica)* | Linha, uma observação por ano |
| **Tamanho estimado** *(em 1 ano)* | < 1 MB / ano (série temporal leve) |
| **Como é lido** *(registro inteiro / poucas colunas / busca por chave)* | Busca pela chave temporal `ano` |
| **Frequência de leitura** | Média (acessado durante treinamento dos modelos analíticos macroeconômicos e geração de relatórios) |
| **Formato proposto** | Manter o JSON gzip na camada raw, Parquet na camada transformada e DuckDB na camada servida. |
| **Justificativa da escolha** | O DuckDB único segue o [ADR 0002](../adr/0002-duckdb-unico.md) e permite junções temporais diretas com `dolar_cotacao` e `commodity_cotacao`. |
| **Ganho esperado** *(se houver troca)* | Zero custo adicional de infraestrutura e latência imperceptível em consultas OLAP. |

Detalhamento campo a campo das tabelas: [Dicionário de Dados — PIB dos EUA](../dicionario/pib_usa.md).

---

## 3. Carga de trabalho

### Taxa de escrita

- **Carga histórica:** Evento único, 2 requisições HTTP, reexecutável.
- **Regime:** 1 registro novo por ano, com possíveis revisões de anos anteriores.
- **Escrita transacional:** Nenhuma. A carga é em lote (batch) e idempotente.

### Taxa de leitura e padrão de acesso

| # | Consulta | Frequência | Tipo | Latência Alvo | Acesso |
|---|---|---|---|---|---|
| 1 | Coleta na API do Banco Mundial | 1 rodada/ano | lote | < 5 s | `api.worldbank.org/v2/country/USA/indicator/...` |
| 2 | Cruzamento temporal PIB EUA x Dólar / Commodities | Média (sob demanda) | agregada | < 300 ms | `JOIN pib_usa u ON year(c.data_referencia) = u.ano` |

---

## 4. Restrições que a origem impõe

- **Frequência de atualização lenta:** Indicadores anuais divulgados com meses de atraso após o encerramento do ano civil.
- **Sem autenticação exigida:** API pública sem exigência de API Key.
