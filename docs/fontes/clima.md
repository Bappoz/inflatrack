# Dados do Clima Diário (INMET)

Este documento registra as características arquiteturais e de negócio para a fonte de dados meteorológicos diários coletados pelo **Instituto Nacional de Meteorologia ([INMET](https://portal.inmet.gov.br/))** a partir de sua rede de estações meteorológicas distribuídas pelo território brasileiro.

## Séries coletadas

O catálogo de estações vem da API REST do INMET (`apitempo.inmet.gov.br/estacoes/T`). As medições vêm dos pacotes anuais do BDMEP (`portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip`, um CSV horário por estação), resumidas por dia: a rota diária da API responde 404 e a horária só devolve vazio sem token ([evidência da E2](../evidencias/e2/clima.md#diagnostico-e-validacao-da-api-do-inmet); carga em [BDMEP](../evidencias/e3/clima_bdmep.md)).

Como o INMET publica o pacote do ano corrente cerca de 1×/mês, os dias entre o último publicado e ontem vêm do **Open-Meteo** como clima **provisório** (ver [seção 6](#6-clima-provisorio-open-meteo)): valores de modelo, guardados à parte e trocados pelo oficial quando ele chega.

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
| **Formato em que chega** *(JSON, CSV, formulário, API...)* | Catálogo: JSON (API REST). Medições: `.zip` anual com um CSV horário por estação (`;`, vírgula decimal, latin-1). |
| **Volume estimado** *(por dia ou por mês)* | Pacote anual de 15 a 90 MB (todas as estações); das 16 estações mapeadas ficam ~1 MB de CSV por estação e ano. |
| **Frequência de chegada** *(tempo real / horária / diária / eventual)* | Leituras horárias; o INMET republica o pacote do ano corrente cerca de 1×/mês (o de 2026 foi atualizado em 2026-11-05). |
| **Vazão** *(alta / média / baixa)* | Alta (centenas de estações ativas transmitindo múltiplos parâmetros ambientais diariamente). |
| **Pureza** *(alta / média / baixa)* | Média (sujeita a instabilidades operacionais em sensores de campo, falhas de telemetria, dados faltantes pontuais ou estações em manutenção/pane temporária, exigindo tratamento de valores ausentes). |
| **Previsibilidade do formato** *(alta / média / baixa)* | Média: o cabeçalho do CSV mudou em 2019 (`DATA (YYYY-MM-DD);HORA (UTC)` virou `Data;Hora UTC`, e `-9999` virou vazio), mas os nomes das medidas mantêm o prefixo. A Bronze localiza as colunas pelo nome. |
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
| **Formato atual** | Respostas e tabelas tipadas em Delta (`data/parquet/clima/resposta/`, `estacao/` e `medicao/`), espelhadas no schema `bronze` do DuckDB; dbt consolida as leituras em `silver.int_clima__anomalia_mensal`. |
| **Texto ou binário** | Texto na origem (JSON e CSV); o Raw guarda o texto em `clima_resposta` (Delta/Parquet, binário colunar). |
| **Orientação** *(linha / coluna / não se aplica)* | Coluna (no DuckDB e no Parquet, otimizado para agregações temporais e espaciais de chuva e temperatura). |
| **Tamanho estimado** *(em 1 ano)* | Raw: ~120 MB / ano comprimido. Silver (DuckDB/Parquet colunar): ~30 a 50 MB / ano considerando as estações ativas agregadas por dia. |
| **Como é lido** *(registro inteiro / poucas colunas / busca por chave)* | Poucas colunas (`data_referencia`, `estacao_id`, `precipitacao`, `temp_max`, `temp_min`) em agregações regionais e filtros temporais, além de buscas por chave no `JOIN` com cotações de commodities. |
| **Frequência de leitura** | Alta (lido intensivamente no pipeline de features dos modelos preditivos de commodities e em notebooks de análise causal de preços de alimentos). |
| **Formato proposto** | Delta Lake append-only para respostas e versões de leituras; DuckDB `bronze.*` como espelho recriável e dbt Silver mensal com métricas e lags por estação. |
| **Justificativa da escolha** | Segue o [ADR 0002](../adr/0002-duckdb-unico.md). Manter o clima no mesmo DuckDB analítico compartilhado permite junções diretas entre cotações de commodities (`commodity_cotacao`), o IPCA de alimentos (`observacao`) e as anomalias de chuva/temperatura em uma única consulta SQL, sem latência de rede. |
| **Ganho esperado** *(se houver troca)* | Alta compressão colunar, agregações temporais (médias móveis de 30 dias de chuva acumulada) calculadas em poucos milissegundos via SQL vetorial. |

---

## 3. Carga de trabalho

### Taxa de escrita

- **Carga histórica:** a primeira coleta (`clima_job` sem config, ou `just clima-ingest`) baixa os pacotes de 2006 até o ano corrente e grava as 16 estações do de-para `dbt/seeds/seed_de_para_estacao_localidade.csv`.
- **Regime:** o `clima_job` roda 1×/dia às 7h (São Paulo). Para cada ano, um `HEAD` no pacote compara `Last-Modified`, tamanho e lista de estações com o manifesto guardado em `clima_resposta`; só baixa o que mudou. Na prática, 21 HEADs por dia e um download quando o INMET republica (≈1×/mês) ou quando o de-para ganha estação.
- **Escrita real vs. custo de coleta:** o CSV de cada estação vai inteiro para `resposta/`; cada dia vira uma linha tipada em `medicao/`. Reexecuções não duplicam (hash do conteúdo) e revisões do INMET entram como versão nova.
- **Escrita transacional:** Nenhuma. O loader espelha a tabela Delta em `bronze.clima_medicao`; a Silver escolhe a revisão mais recente por estação e dia.
- **Falha parcial:** um ano que falha não impede os outros e não grava manifesto, então é refeito na execução seguinte; a coleta termina com código 1 e o run fica vermelho. Contam como falha: erro de rede, zip corrompido, pacote de ano já encerrado que sumiu do portal (404), pacote sem nenhuma das estações pedidas e CSV recusado (coluna faltando ou código do cabeçalho diferente do nome do arquivo). Um CSV recusado não descarta os das outras estações. Estação ausente só em alguns anos (começou depois, parou antes) é aviso.
- **Provisório (Open-Meteo):** no mesmo `clima_job`, depois do BDMEP, uma chamada ao Open-Meteo traz as 16 estações, do dia seguinte ao último oficial até ontem (no máximo 92 dias). A janela inteira é relida todo dia, porque o Open-Meteo troca a previsão pela reanálise ERA5 nos dias recentes; o hash do conteúdo evita duplicar o que não mudou.
- **Mudança na regra de leitura:** `VERSAO_LEITURA` entra no manifesto; ao subir o número, a coleta seguinte relê todos os pacotes uma vez, e só as leituras com valor diferente viram versão nova.

### Execução e preparação do banco

- `just clima`: coleta catálogo e medições e promove as duas tabelas Delta ao DuckDB.
- `just bronze-clima`: só o catálogo de estações.
- `just clima-provisorio`: só o provisório do Open-Meteo e a carga dele no DuckDB.
- Recorte manual: `uv run python -m inflatrack.bronze.clima coletar --medicoes --estacao A001 --de-ano 2020 --ate-ano 2021` (repita `--estacao`), depois `just clima-load`. No Dagster, `clima_medicoes` aceita os campos opcionais `estacoes`, `ano_inicio` e `ano_fim`.
- As cargas `clima_duckdb` e `clima_medicoes_duckdb` aplicam `scripts/sql/setup_duckdb_clima.sql` antes de carregar (`load_clima --tabela estacao|medicao`), então as duas tabelas existem para o dbt mesmo antes da primeira coleta. Fora do Dagster, `just duckdb-init` faz o mesmo sem API nem Delta (idempotente, respeita `DBT_DUCKDB_PATH`, não apaga dados) e `just dbt` já o chama.

### Taxa de leitura e padrão de acesso

| # | Consulta | Frequência | Tipo | Latência Alvo | Acesso |
|---|---|---|---|---|---|
| 1 | Coleta das medições no BDMEP | 1 rodada/dia | lote | < 5 s sem mudança; ~15 s por pacote baixado | HEAD por pacote anual; GET só do pacote republicado |
| 2 | Precipitação acumulada de 30/60 dias por polo agrícola | Alta (modelos de ML) | agregada | < 150 ms | `SELECT estacao_id, sum(precipitacao) FROM clima_diario WHERE data_referencia >= ... GROUP BY estacao_id` |
| 3 | Cruzamento Anomalia Climática x Preço de Commodities Agrícolas | Média (notebooks/estudos) | agregada | < 250 ms | `JOIN clima_diario c ON c.data_referencia = m.data_referencia` com `commodity_cotacao` (Milho, Trigo, Café) |
| 4 | Monitoramento de geadas e extremos térmicos | Baixa (eventual) | pontual | < 50 ms | `SELECT * FROM clima_diario WHERE temp_min <= 2.0 AND data_referencia >= ...` |

---

## 4. Restrições que a origem impõe

- **Instabilidade e disponibilidade da API governamental:** A API do INMET desativou a rota diária e exige token na horária; só o catálogo segue aberto. O BDMEP é estável, mas tem defasagem: o pacote do ano corrente é republicado cerca de 1×/mês. O cliente usa *timeouts* explícitos e o Dagster repete a coleta (`RETRY_REDE`).
- **Estações com dados ausentes (*gaps*):** Sensores de campo em estações remotas sofrem manutenções ou falhas elétricas, gerando lacunas temporárias (`null`). O pipeline analítico deve prever imputação ou agregação regional ponderada para evitar propagação de nulos nos modelos de Machine Learning.
- **Volume por requisição:** o pacote anual traz todas as ~600 estações (até 90 MB), mesmo que só 16 interessem. Ele é baixado em streaming para um arquivo temporário e descartado depois de extrair os CSVs mapeados.
- **Heterogeneidade de estações:** A malha do INMET compreende estações **automáticas** (telemetria digital contínua) e **convencionais** (leituras analógicas manuais). O pipeline prioriza estações automáticas pela maior granularidade e menor latência de publicação.
- **Necessidade de mapeamento espacial:** As medições climáticas precisam ser vinculadas geograficamente aos municípios e polos agrícolas produtores de commodities (via metadados cadastrais de estações: código, latitude, longitude e estado).

## 5. Modelo mensal e vínculo com o IPCA

`silver.int_clima__anomalia_mensal` apresenta uma linha por estação x mês, com médias, extremos,
desvios-padrão, precipitação acumulada, contagem de dias, anomalia contra a normal dos anos
anteriores e defasagens de um a três meses. A chuva do mês só sai com ao menos 80% dos dias
medidos, para uma falha de sensor não parecer seca.

`gold.fct_clima_mensal` leva isso para o grão praça do IPCA x mês, com a grade completa de meses,
lags calculados sobre a série da praça e `mes_fechado` para tirar do treino o mês ainda não
publicado. O relacionamento com as praças fica em `dbt/seeds/seed_de_para_estacao_localidade.csv`:
16 estações para as 16 praças regionais (o Brasil não tem estação). Fortaleza usa a A305, que
existe no BDMEP mas não está mais no catálogo da API e quase não mediu em 2025; Recife (A301)
sumiu do pacote de 2025. A cobertura real por estação está na
[evidência da carga](../evidencias/e3/clima_bdmep.md).

Vazio, `-9999` e valores fora da faixa física viram `NULL`; zero é leitura válida e fica zero.

## 6. Clima provisório (Open-Meteo)

| Atributo | Resposta |
| :--- | :--- |
| **Fonte** | [Open-Meteo](https://open-meteo.com/), `archive-api.open-meteo.com/v1/archive` (o *best match* junta a reanálise ERA5, com ~5 dias de atraso, e a análise do ECMWF IFS até ontem) |
| **Custo e licença** | Grátis, sem chave, para uso não comercial (projeto acadêmico, sem anúncio nem assinatura). Dados sob CC BY 4.0: citar *Weather data by Open-Meteo.com*. Limite de 10 mil chamadas por dia; a coleta faz 1. |
| **O que é** | Valor de **modelo em grade** no ponto da estação (coordenadas no seed de-para, tiradas do CSV do BDMEP), não medição. O dia é UTC (`timezone=GMT`), como no BDMEP. |
| **Quando entra** | Só nos dias **depois do último dia publicado pelo INMET** e até ontem. Nunca preenche buraco do histórico oficial, nem de estação parada no passado. |
| **Onde fica** | Raw: o JSON em `clima_resposta`. Bronze: Delta `data/parquet/clima/medicao_provisoria/` e `bronze.clima_medicao_provisoria`, à parte de `clima_medicao`. Silver: `stg_clima__medicao_diaria` com `fonte = 'open_meteo'` e `observado = false`. Gold: `dias_provisorios` em `fct_clima_mensal`. |
| **Quando sai** | Sozinho: quando o pacote do INMET chega, o corte avança e a staging descarta o provisório daqueles dias. Ele continua no Delta (só acrescenta), para auditoria. |

**Quão perto do medido.** Comparação mensal em Brasília (A001), nov/2025 a out/2026: a
temperatura média do Open-Meteo ficou 0,1 a 0,7 °C acima da do INMET em todos os meses; a chuva
divergiu muito mês a mês (275 mm medidos contra 134 mm do modelo em nov/2025, 79 contra 204 em
fev/2026), porque chuva de verão é localizada e o modelo dá a média de uma célula de vários km.
Por isso:

- **para treinar o modelo**, use só `mes_fechado = true`: nenhum mês com dia provisório está
  fechado;
- **para prever o mês corrente**, a temperatura provisória é confiável; a chuva provisória é
  só indicativa, e a anomalia do mês em curso pode sair levemente positiva pelo viés de
  temperatura do modelo.
