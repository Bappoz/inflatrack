# Dados do Clima Diário (INMET)

Este documento registra as características arquiteturais e de negócio para a fonte de dados meteorológicos diários coletados pelo **Instituto Nacional de Meteorologia ([INMET](https://portal.inmet.gov.br/))** a partir de sua rede de estações meteorológicas distribuídas pelo território brasileiro.

## Séries coletadas

As medições meteorológicas são obtidas via API REST do INMET (`apitempo.inmet.gov.br` / `portal.inmet.gov.br`):

| Indicador | Descrição | Unidade | Frequência de acesso |
|---|---|---|---|
| `temp_min` | Temperatura mínima registrada no dia | Graus Celsius (°C) | Diária |
| `temp_max` | Temperatura máxima registrada no dia | Graus Celsius (°C) | Diária |
| `precipitacao_total` | Precipitação acumulada de chuva | Milímetros (mm) | Diária |
| `umidade_relativa_media` | Umidade relativa do ar média compensada | Percentual (%) | Diária |
| `umidade_relativa_min` | Umidade relativa do ar mínima do dia | Percentual (%) | Diária |

A coleta prioriza as estações meteorológicas localizadas nos principais polos e cinturões agrícolas do país (Centro-Oeste, Sul, Sudeste e Matopiba). Esses dados funcionam como variáveis explicativas e antecedentes para os preços de commodities agrícolas cotadas no projeto (como Milho, Trigo, Café, Açúcar e Algodão) e para o subgrupo de Alimentação e Bebidas do IPCA/INPC.

---

## 1. Fonte de Origem

| Atributo | Resposta |
| :--- | :--- |
| **Nome da fonte** | Dados do clima diário |
| **Tipo** *(usuário / sistema / interna / terceiro)* | Terceiro |
| **Quem ou o que gera** | Instituto Nacional de Meteorologia (INMET) |
| **O que essa fonte contém** | Temperatura (mínima e máxima), precipitação (chuva em mm) e umidade relativa do ar apuradas pelas estações meteorológicas automáticas e convencionais. |
| **Formato em que chega** *(JSON, CSV, formulário, API...)* | JSON (via API REST) |
| **Volume estimado** *(por dia ou por mês)* | ~10 MB por mês (somatório das respostas diárias com as medições consolidadas da malha de estações operantes). |
| **Frequência de chegada** *(tempo real / horária / diária / eventual)* | Diária (fechamento diário consolidado das medições das estações). |
| **Vazão** *(alta / média / baixa)* | Alta (centenas de estações ativas transmitindo múltiplos parâmetros ambientais diariamente). |
| **Pureza** *(alta / média / baixa)* | Média (sujeita a instabilidades operacionais em sensores de campo, falhas de telemetria, dados faltantes pontuais ou estações em manutenção/pane temporária, exigindo tratamento de valores ausentes). |
| **Previsibilidade do formato** *(alta / média / baixa)* | Alta (contrato de resposta JSON padronizado pelo INMET com chaves fixas para estação, data e parâmetros meteorológicos). |
| **Contém dado pessoal?** *(sim / não)* | Não |
| **Base legal LGPD** *(se contém dado pessoal)* | Não se aplica (dados ambientais, geográficos e climáticos públicos). |
| **Retenção** *(por quanto tempo guardar)* | Permanente (séries climáticas históricas contínuas são essenciais para capturar sazonalidade, anomalias climáticas como El Niño/La Niña e treinar modelos preditivos de safras). |
| **O que quebra se essa fonte falhar** | O clima impacta diretamente a colheita de commodities. Sem essa fonte, a análise perde a capacidade de explicar a variação brusca de preços agrícolas provocada por secas, geadas ou chuvas torrenciais. |

---

## 2. Conjunto de Dados / Armazenamento

| Atributo | Resposta |
| :--- | :--- |
| **Conjunto de dados** | Séries Históricas de Dados Climáticos e Meteorológicos Diários (Raw / Silver) |
| **Fonte de origem** *(nº da aba 1)* | INMET - Instituto Nacional de Meteorologia |
| **Formato atual** | `.json.gz` na camada raw (`data/raw/inmet/`), `.parquet` na camada silver (`data/parquet/clima/`) e tabelas `estacao_meteorologica` e `clima_diario` no DuckDB analítico compartilhado (`data/duckdb/inflatrack.duckdb`). |
| **Texto ou binário** | Binário (o raw é JSON comprimido em gzip; Parquet e DuckDB são formatos binários colunares de alto desempenho). |
| **Orientação** *(linha / coluna / não se aplica)* | Coluna (no DuckDB e no Parquet, otimizado para agregações temporais e espaciais de chuva e temperatura). |
| **Tamanho estimado** *(em 1 ano)* | Raw: ~120 MB / ano comprimido. Silver (DuckDB/Parquet colunar): ~30 a 50 MB / ano considerando as estações ativas agregadas por dia. |
| **Como é lido** *(registro inteiro / poucas colunas / busca por chave)* | Poucas colunas (`data_referencia`, `estacao_id`, `precipitacao`, `temp_max`, `temp_min`) em agregações regionais e filtros temporais, além de buscas por chave no `JOIN` com cotações de commodities. |
| **Frequência de leitura** | Alta (lido intensivamente no pipeline de features dos modelos preditivos de commodities e em notebooks de análise causal de preços de alimentos). |
| **Formato proposto** | Manter o padrão Medallion do repositório: arquivos brutos `.json.gz` particionados por data na camada raw, transformação colunar em Parquet particionado e carregamento incremental idempotente na tabela `clima_diario` no DuckDB. |
| **Justificativa da escolha** | Segue o [ADR 0002](../adr/0002-duckdb-unico.md). Manter o clima no mesmo DuckDB analítico compartilhado permite junções diretas entre cotações de commodities (`commodity_cotacao`), o IPCA de alimentos (`observacao`) e as anomalias de chuva/temperatura em uma única consulta SQL, sem latência de rede. |
| **Ganho esperado** *(se houver troca)* | Alta compressão colunar, agregações temporais (médias móveis de 30 dias de chuva acumulada) calculadas em poucos milissegundos via SQL vetorial. |

---

## 3. Carga de trabalho

### Taxa de escrita

- **Carga histórica:** Coleta em lote por estação ou blocos de períodos via API / BDMEP do INMET, materializando o histórico recente no raw e inserindo no DuckDB via `UPSERT` idempotente.
- **Regime:** 1 rodada diária consultando as medições consolidadas do dia anterior de ~600 estações operantes (~600 linhas diárias na tabela silver, ~18.000 linhas/mês).
- **Escrita real vs. custo de coleta:** A rodada diária baixa ~300-400 KB de JSONs da API, arquiva o raw comprimido e faz `UPSERT` por `(estacao_id, data_referencia)` na base analítica.
- **Escrita transacional:** Nenhuma. Carga em lote (batch diário), idempotente com resolução de conflito (`ON CONFLICT DO UPDATE`).

### Taxa de leitura e padrão de acesso

| # | Consulta | Frequência | Tipo | Latência Alvo | Acesso |
|---|---|---|---|---|---|
| 1 | Coleta diária de medições na API do INMET | 1 rodada/dia | lote | < 30 s | Requisições HTTP REST aos endpoints de dados diários por estação/data |
| 2 | Precipitação acumulada de 30/60 dias por polo agrícola | Alta (modelos de ML) | agregada | < 150 ms | `SELECT estacao_id, sum(precipitacao) FROM clima_diario WHERE data_referencia >= ... GROUP BY estacao_id` |
| 3 | Cruzamento Anomalia Climática x Preço de Commodities Agrícolas | Média (notebooks/estudos) | agregada | < 250 ms | `JOIN clima_diario c ON c.data_referencia = m.data_referencia` com `commodity_cotacao` (Milho, Trigo, Café) |
| 4 | Monitoramento de geadas e extremos térmicos | Baixa (eventual) | pontual | < 50 ms | `SELECT * FROM clima_diario WHERE temp_min <= 2.0 AND data_referencia >= ...` |

---

## 4. Restrições que a origem impõe

- **Instabilidade e disponibilidade da API governamental:** A infraestrutura de API do INMET está sujeita a instabilidades eventuais, limites de taxa não declarados e lentidão em horários de pico, exigindo cliente HTTP com *timeouts* explícitos e política de retentativas defensivas.
- **Estações com dados ausentes (*gaps*):** Sensores de campo em estações remotas sofrem manutenções ou falhas elétricas, gerando lacunas temporárias (`null`). O pipeline analítico deve prever imputação ou agregação regional ponderada para evitar propagação de nulos nos modelos de Machine Learning.
- **Paginação e limites temporais por requisição:** Consultas históricas extensas na API exigem particionamento em blocos temporais menores (*chunks* de até 1 ano por estação), evitando requisições muito pesadas que provoquem *timeouts* no servidor do instituto.
- **Heterogeneidade de estações:** A malha do INMET compreende estações **automáticas** (telemetria digital contínua) e **convencionais** (leituras analógicas manuais). O pipeline prioriza estações automáticas pela maior granularidade e menor latência de publicação.
- **Necessidade de mapeamento espacial:** As medições climáticas precisam ser vinculadas geograficamente aos municípios e polos agrícolas produtores de commodities (via metadados cadastrais de estações: código, latitude, longitude e estado).
