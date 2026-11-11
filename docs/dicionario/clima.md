# Dados do Clima Diário (INMET) — Dicionário de Dados

## Contexto

Esta seção detalha o schema físico dos dados meteorológicos coletados pela rede de estações do Instituto Nacional de Meteorologia (INMET), armazenados no banco analítico compartilhado (**DuckDB** em `data/duckdb/inflatrack.duckdb`), em conformidade com o [ADR 0002](../adr/0002-duckdb-unico.md).

As medições climáticas funcionam como variáveis explicativas e antecedentes para modelos de machine learning, permitindo identificar quebras de safra, secas severas ou geadas que afetam as cotações de commodities agrícolas (`commodity_cotacao`) e o subgrupo de Alimentação e Bebidas do IPCA.

---

## Modelo Conceitual

O modelo meteorológico adota a separação dimensional clássica entre o cadastro cadastral das estações e as medições temporais diárias:

<div class="diagrama">
--8<-- "docs/assets/diagramas/esquema-clima.svg"
</div>

A seta é tracejada porque o DDL (`scripts/sql/setup_duckdb_clima.sql`) não declara a chave estrangeira: a ligação por `estacao_id` é garantida pela carga, não pelo banco.

---

## Entidades

### Tabela: `estacao_meteorologica`

Dimensão cadastral que registra os metadados e coordenadas geográficas de cada estação da malha nacional do INMET.

| Coluna | Tipo (DuckDB) | Chave | Descrição |
|---|---|---|---|
| `estacao_id` | `VARCHAR(10)` | PK | Código identificador único da estação cadastrado no INMET/OMM (ex.: `A001`, `A472`). |
| `nome` | `VARCHAR` | | Nome da localidade ou município onde a estação está instalada (ex.: `BRASILIA`, `ACAJUTIBA`). |
| `estado` | `VARCHAR(2)` | | Sigla da Unidade Federativa (UF) da estação (ex.: `DF`, `BA`, `MT`, `PR`). |
| `tipo` | `VARCHAR(20)` | | Tipo de operação: `Automatica` (digital com telemetria contínua) ou `Convencional` (analógica manual). |
| `latitude` | `DOUBLE` | | Latitude geográfica em graus decimais (WGS 84). |
| `longitude` | `DOUBLE` | | Longitude geográfica em graus decimais (WGS 84). |
| `altitude_m` | `DOUBLE` | | Altitude do ponto de coleta em relação ao nível do mar (em metros). |
| `situacao` | `VARCHAR(20)` | | Situação operacional da estação no momento da sincronização (`Operante`, `Pane`). |

### Tabela: `clima_diario`

Tabela de fato com granularidade diária por estação, acumulando medições de temperatura, chuva e umidade.

| Coluna | Tipo (DuckDB) | Chave | Descrição |
|---|---|---|---|
| `estacao_id` | `VARCHAR(10)` | PK, FK | Código da estação meteorológica de origem (FK para `estacao_meteorologica.estacao_id`). |
| `data_referencia` | `DATE` | PK | Data civil da medição consolidada (`YYYY-MM-DD`). |
| `temp_min` | `DOUBLE` | | Temperatura mínima registrada no dia (em °C). |
| `temp_max` | `DOUBLE` | | Temperatura máxima registrada no dia (em °C). |
| `temp_media` | `DOUBLE` | | Temperatura média diária apurada (em °C). |
| `precipitacao_total_mm` | `DOUBLE` | | Volume acumulado de chuva no dia (em milímetros). |
| `umidade_relativa_media_pct` | `DOUBLE` | | Umidade relativa do ar média observada no dia (em %). |
| `umidade_relativa_min_pct` | `DOUBLE` | | Menor nível de umidade relativa registrado no dia (em %). |
| `observado` | `BOOLEAN` | | `true` se coletado diretamente dos sensores; `false` se preenchido/imputado por interpolação regional. |

---

## Consultas de Exemplo

### 1. Precipitação Acumulada nos Últimos 30 Dias nos Cinturões Produtores

```sql
SELECT 
    e.estado,
    e.nome AS estacao,
    round(sum(c.precipitacao_total_mm), 1) AS chuva_acumulada_30d_mm,
    round(avg(c.temp_media), 1) AS temp_media_30d_c
FROM clima_diario c
JOIN estacao_meteorologica e ON e.estacao_id = c.estacao_id
WHERE e.estado IN ('MT', 'GO', 'MS', 'PR')
  AND c.data_referencia >= CURRENT_DATE - INTERVAL 30 DAYS
GROUP BY e.estado, e.nome
ORDER BY chuva_acumulada_30d_mm ASC;
```

### 2. Cruzamento de Choques Climáticos com Preço de Commodities Agrícolas

Avalia a relação entre secas ou geadas e as cotações de milho, café ou trigo:

```sql
SELECT 
    c.data_referencia,
    round(avg(c.precipitacao_total_mm), 2) AS media_chuva_brasil_mm,
    round(min(c.temp_min), 1) AS temperatura_minima_nacional_c,
    p.preco AS preco_milho_usd
FROM clima_diario c
JOIN commodity_cotacao p ON p.data_referencia = c.data_referencia AND p.symbol = 'CORN'
WHERE c.data_referencia >= '2024-01-01'
GROUP BY c.data_referencia, p.preco
ORDER BY c.data_referencia DESC;
```

---

## Bronze em Delta

As tabelas da fonte meteorológica gravadas pelo ingestor em `data/parquet/clima/`, em formato Delta. Ficam no Delta e substituem os arquivos `.json.gz` de `data/raw/inmet/`. Quando necessário, o DuckDB lê com `delta_scan`.

### clima_resposta

Armazena a resposta original de cada coleta. Uma linha por resposta **diferente** (deduplicada por `hash_corpo`). Três tipos, pelo `tipo_conteudo`:

- `application/json` com `_requisicao` em `/estacoes/T`: o catálogo de estações da API;
- `text/csv; charset=iso-8859-1`: o CSV horário de uma estação dentro do pacote anual do BDMEP, na íntegra (`_requisicao` = `{url do zip}#{arquivo no zip}`);
- `application/json; charset=utf-8` com `_requisicao` = URL do zip: o **manifesto** do pacote processado (`Last-Modified`, tamanho e lista de estações). Se o manifesto já existe, a coleta seguinte não baixa o pacote de novo.

| Campo | Tipo | Descrição |
|---|---|---|
| `id_resposta` | string | Identificador da resposta: o hash SHA-256 do corpo |
| `_fonte` | string | Sempre `"clima"` |
| `_requisicao` | string | URL consultada (API do INMET ou pacote do BDMEP com o arquivo após `#`) |
| `_ingerido_em` | timestamp (UTC) | Momento do download da resposta |
| `status_http` | smallint, nulo | Status HTTP da resposta (200, ou nulo se importado do Raw) |
| `tipo_conteudo` | string, nulo | `Content-Type` do cabeçalho HTTP |
| `corpo` | string | O conteúdo original na íntegra (JSON ou CSV) |
| `hash_corpo` | string | SHA-256 do corpo (idempotência) |
| `tamanho_bytes` | bigint | Tamanho do payload em bytes |

### clima_estacao

Cadastro nacional das estações meteorológicas (automáticas e convencionais) ativas e inativas. Não inventa valores padrão: campos não informados pelo INMET permanecem nulos.

| Campo | Tipo | Origem na API | Descrição |
|---|---|---|---|
| `estacao_id` | string | `CD_ESTACAO` | Código alfanumérico identificador único (ex.: `A001`, `A472`) |
| `nome` | string | `DC_NOME` | Nome do município ou ponto de medição |
| `estado` | string | `SG_ESTADO` | Sigla da Unidade Federativa (UF) |
| `tipo` | string, nulo | `TP_ESTACAO` | Tipo da estação (`"Automatica"` ou nulo) |
| `latitude` | double, nulo | `VL_LATITUDE` | Latitude geográfica decimal (WGS 84) |
| `longitude` | double, nulo | `VL_LONGITUDE` | Longitude geográfica decimal (WGS 84) |
| `altitude_m` | double, nulo | `VL_ALTITUDE` | Altitude da estação em metros |
| `situacao` | string, nulo | `CD_SITUACAO` | Situação operacional (`"Operante"`, `"Pane"` ou nulo) |
| `data_inicio_operacao` | string, nulo | `DT_INICIO_OPERACAO` | Data/hora de início de operação registrada |
| `data_fim_operacao` | string, nulo | `DT_FIM_OPERACAO` | Data/hora de desativação (se aplicável) |
| `_id_resposta` | string | — | Chave estrangeira para `clima_resposta.id_resposta` |
| `_fonte` | string | — | Sempre `"clima"` |
| `_requisicao` | string | — | URL da chamada |
| `_ingerido_em` | timestamp (UTC) | — | Momento da ingestão |

**Granularidade:** uma linha por estação meteorológica × atributos operacionais. Atualizações cadastrais pelo INMET geram uma nova versão rastreável em Delta (*insert-only*).

### clima_medicao

Tabela Delta em `data/parquet/clima/medicao/`, com uma linha por versão de leitura diária, resumida
das 24 leituras horárias do CSV do BDMEP no dia UTC (o BDMEP publica em UTC; hora repetida no CSV
conta uma vez, valendo a última linha). Cada métrica só sai
com ao menos 18 horas válidas (`HORAS_MINIMAS`); vazio, `-9999` e valores fora da faixa física
(temperatura de -15 a 50 °C, chuva de 0 a 200 mm/h, umidade de 0 a 100%) viram nulo. O campo
`id_medicao` é calculado a partir dos valores da leitura, sem incluir metadados de ingestão; assim,
uma reexecução idêntica não duplica linhas e uma revisão histórica é preservada como versão nova.

O loader espelha a tabela em `bronze.clima_medicao`, criada por
`scripts/sql/setup_duckdb_clima.sql`. O script SQL é necessário ao loader e não deve ser removido.
Na Silver, a leitura mais recente por estação e dia alimenta a consolidação mensal, com defasagens
`t-1`, `t-2` e `t-3`. Campos ausentes e sentinelas viram `NULL`; zeros reais permanecem zero.

| Campo | Tipo | Origem no CSV do BDMEP | Descrição |
|---|---|---|---|
| `id_medicao` | string | — | SHA-256 dos valores da leitura (inclui `horas_com_registro`) |
| `estacao_id` | string | `CODIGO (WMO)` | Código INMET da estação |
| `data_referencia` | date | `Data` / `DATA (YYYY-MM-DD)` | Dia UTC |
| `temp_min` | double, nulo | `TEMPERATURA MÍNIMA NA HORA ANT.` | Menor mínima horária do dia (°C) |
| `temp_max` | double, nulo | `TEMPERATURA MÁXIMA NA HORA ANT.` | Maior máxima horária do dia (°C) |
| `temp_media` | double, nulo | `TEMPERATURA DO AR - BULBO SECO, HORARIA` | Média das temperaturas horárias (°C) |
| `precipitacao_total_mm` | double, nulo | `PRECIPITAÇÃO TOTAL, HORÁRIO` | Soma da chuva horária (mm) |
| `umidade_relativa_media_pct` | double, nulo | `UMIDADE RELATIVA DO AR, HORARIA` | Média da umidade horária (%) |
| `umidade_relativa_min_pct` | double, nulo | `UMIDADE REL. MIN. NA HORA ANT.` | Menor umidade mínima horária (%) |
| `horas_com_registro` | smallint | — | Horas do dia com ao menos uma medida válida |
| `observado` | boolean | — | Sempre verdadeiro: leitura medida, não estimada |
| `_id_resposta` | string | — | Chave para `clima_resposta.id_resposta` (o CSV de origem) |
| `_fonte`, `_requisicao`, `_ingerido_em` | — | — | Procedência, como nas demais tabelas |

### clima_medicao_provisoria

Tabela Delta em `data/parquet/clima/medicao_provisoria/`, espelhada em
`bronze.clima_medicao_provisoria`. Uma linha por versão de dia provisório do Open-Meteo para os
dias que o INMET ainda não publicou. Mesmas medidas de `clima_medicao` (`temp_min`, `temp_max`,
`temp_media`, `precipitacao_total_mm`, `umidade_relativa_media_pct`, `umidade_relativa_min_pct`),
mais:

| Campo | Tipo | Descrição |
|---|---|---|
| `id_medicao` | string | SHA-256 dos valores do dia (uma revisão do modelo vira linha nova) |
| `latitude_grade`, `longitude_grade` | double | Ponto da grade do modelo que o Open-Meteo usou |
| `fonte` | string | Sempre `open_meteo` |
| `_id_resposta` | string | Chave para o JSON original em `clima_resposta` |

### Silver: `silver.stg_clima__medicao_diaria`

Uma linha por estação x dia: a última revisão do INMET e, só depois do último dia oficial, o
provisório. `fonte` diz de onde veio (`inmet_bdmep` ou `open_meteo`) e `observado` é falso no
provisório. `horas_com_registro` fica nulo no provisório (não há leitura horária).

## Gold: `gold.fct_clima_mensal`

Uma linha por praça do IPCA x mês, do primeiro ao último mês com medição. É a tabela de clima do
modelo preditivo e se junta a `gold.fct_inflacao_mensal` por `(codigo_localidade, mes_referencia)`.
A praça vem de `dbt/seeds/seed_de_para_estacao_localidade.csv` (uma estação por praça; o Brasil não
entra). Nenhuma coluna usa meses futuros: as normais climatológicas são só dos anos anteriores.

| Campo | Descrição |
|---|---|
| `codigo_localidade`, `mes_referencia` | Chave (FK para `dim_localidade` e `dim_calendario`) |
| `mes_fechado` | Falso no mês que o INMET ainda não publicou inteiro (inclui todo mês com dia provisório): não usar no treino |
| `dias_provisorios` | Dias do mês cobertos pelo Open-Meteo enquanto o INMET não publica |
| `estacoes_com_dado`, `dias_com_registro`, `dias_no_mes`, `cobertura_dias` | Cobertura do mês (0 a 1) |
| `temp_media`, `temp_min_absoluta`, `temp_max_absoluta` | Temperatura média e extremos (°C) |
| `temp_media_anomalia` | Temperatura menos a normal do mesmo mês nos anos anteriores (mín. 3 anos) |
| `precipitacao_total_mm`, `dias_com_chuva` | Chuva do mês; nulos com menos de 80% dos dias medidos |
| `precipitacao_anomalia_mm` | Chuva menos a normal do mesmo mês nos anos anteriores |
| `umidade_relativa_media_pct` | Umidade média (%) |
| `*_t_menos_1`, `*_t_menos_2`, `*_t_menos_3`, `temp_media_mm3` | Lags de 1 a 3 meses de calendário e média móvel de 3 meses |

