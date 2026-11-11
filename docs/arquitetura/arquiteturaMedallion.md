# Arquitetura Medallion

O Medallion é a arquitetura do pipeline analítico do InflaTrack e está
implementado até a Gold e a vitrine desde a Entrega 3: a Bronze é Delta Lake, a
Silver e a Gold são modelos dbt no DuckDB, e uma cópia da Gold vai para o schema
`serie` do PostgreSQL, que o Metabase lê. Nem toda fonte chegou à Gold: PIB do
Brasil e commodities têm Silver mensal, mas ainda não têm fato próprio na Gold. A camada semântica das métricas é da Entrega 4.

O PostgreSQL roda em paralelo e guarda o lado transacional — cadastro e
histórico de reajustes — além da referência atual do IPCA/INPC. Ele não é uma
camada do Medallion.

## As quatro camadas

| Camada | Tecnologia | Papel | Estado no repositório |
|---|---|---|---|
| **Raw** | Resposta original de cada coleta, com o SHA-256 do corpo, na tabela `<fonte>_resposta` do Delta (desde a E3). Os `.json.gz`/`.html.gz` em `data/raw/<fonte>/` são o formato antigo, ainda lidos pelos comandos `importar`. | Preservar a entrada para auditoria e reprocessamento. | Em uso. A coleta do salário mínimo ainda grava também o HTML em `data/raw/dieese/`; cargas históricas importadas podem conter respostas reserializadas pelo fluxo antigo. |
| **Bronze** | Tabelas Delta Lake sobre Parquet em `data/parquet/<fonte>/`, espelhadas em `bronze.*` no DuckDB pelos loaders. | Guardar payload tipado por fonte, ainda sem regra analítica comum. | Em uso em todas as fontes. O Parquet simples só sobra na coleta legada do salário mínimo. |
| **Silver** | Modelos SQL em `dbt-duckdb`: `stg_*` (limpeza 1:1) e `int_*__mensal` (grão mensal, `mes_referencia` no dia 1), em `dbt/models/staging` e `intermediate`. | Limpar, deduplicar e conformar cada fonte. | Em uso (E3), com testes dbt de unicidade, não nulo, integridade e volume. |
| **Gold** | Tabelas analíticas no DuckDB produzidas a partir de `dbt/models/marts/`: `dim_calendario`, `dim_localidade`, `dim_cesta_ipca_scd2`, `dim_produto_preco_scd2`, `fct_inflacao_mensal`, `fct_macroeconomia_mensal`, `fct_salario_minimo_mensal`, `fct_pib_internacional_anual`, `fct_clima_mensal` e `fct_reajuste_lojista`. | Cruzar as fontes e fornecer métricas para painel e análise. | Em uso (E3), com SCD tipo 2 na cesta do IPCA e no preço do lojista. As tabelas que o painel lê são copiadas para `serie` pelo ativo `serie_postgres`. |

<div class="diagrama">
--8<-- "docs/assets/diagramas/medallion.svg"
</div>

## Bronze atual por fonte

O diretório `data/parquet/` é o nome histórico compartilhado. Nas fontes
migradas, as subpastas contêm tabelas Delta (arquivos Parquet e log
`_delta_log`); não são necessariamente arquivos `.parquet` independentes.

| Fonte | Resposta original (Raw) | Bronze implementada |
|---|---|---|
| [IPCA/INPC (SIDRA)](../fontes/sidra.md) | `ipca_resposta` no Delta | Delta em `data/parquet/ipca/` (`ipca_resposta`, `ipca_observacao`, `ipca_metadados`) |
| [Commodities e Energia](../fontes/commodities.md) | `commodities_resposta` no Delta | Delta em `data/parquet/commodities/` (`commodities_resposta`, `commodities_cotacao`) |
| [Dólar Comercial](../fontes/dolar.md) | `dolar_resposta` no Delta | Delta em `data/parquet/dolar/` (`dolar_resposta`, `dolar_boletim`) |
| [Taxa SELIC](../fontes/selic.md) | `selic_resposta` no Delta | Delta em `data/parquet/selic/` |
| [PIB e Setores (SIDRA 1846)](../fontes/pib.md) | `pib_resposta` no Delta | Delta em `data/parquet/pib/` (`pib_resposta`, `pib_valor`) |
| [PIB da China](../fontes/pib_china.md) | resposta guardada no Delta | Delta em `data/parquet/pib_china/`; o loader unifica os três países em `bronze.pib_internacional_indicador` |
| [PIB dos EUA](../fontes/pib_usa.md) | resposta guardada no Delta | Delta em `data/parquet/pib_usa/` |
| [PIB da Rússia](../fontes/pib_russia.md) | resposta guardada no Delta | Delta em `data/parquet/pib_russia/` |
| [Salário Mínimo (DIEESE)](../fontes/salario_minimo.md) | `salario_minimo_resposta` no Delta; HTML também em `data/raw/dieese/` | Delta em `data/parquet/salario_minimo/` (`salario_minimo_resposta`, `salario_minimo_mes`); o fluxo legado ainda grava `data/parquet/dieese/` |
| [Dados do Clima (INMET)](../fontes/clima.md) | `clima_resposta` no Delta: JSON do catálogo e o CSV de cada estação dos pacotes anuais do BDMEP | Delta em `data/parquet/clima/` (`clima_resposta`, `clima_estacao`, `clima_medicao`) |

## Fluxo

**Origem → Raw.** A resposta é guardada antes de ser interpretada,
para que uma transformação possa ser refeita sem consultar a API. O histórico
importado pode ter limitações: por exemplo, parte dos arquivos antigos do SIDRA
foi reserializada pelo ingestor anterior, conforme a [evidência da E2](../evidencias/e2/ipca.md#importacao-do-raw-antigo).

**Raw → Bronze.** O ingestor interpreta o formato de cada origem, tipa os
campos e registra procedência. Em todas as fontes, Delta Lake registra commits e
versões sobre os arquivos Parquet; hashes e chaves na lógica de ingestão
permitem reexecuções idempotentes, e uma revisão da fonte entra como linha nova
(*insert-only*). O loader espelha o Delta em `bronze.*` no DuckDB.

**Bronze → Silver.** O dbt trata marcadores de ausência (`valor` nulo e o texto
original em `valor_bruto`), deduplica revisões e alinha chaves, e agrega cada
fonte ao grão mensal com `mes_referencia` no dia 1. Dólar e Selic entram só com os
dias úteis publicados (a Silver conta `dias_uteis_dolar` e `dias_uteis_selic`): o
calendário civil com `forward fill` do [ADR 0003](../adr/0003-bcb-macro.md) não foi
migrado para o dbt, e os carregadores que o faziam foram removidos.

**Silver → Gold.** Os modelos cruzam as fontes por `mes_referencia`, via
`dim_calendario`, em fatos e dimensões com granularidade declarada. A cesta do
IPCA e o preço do lojista são SCD tipo 2 (`dim_cesta_ipca_scd2`,
`dim_produto_preco_scd2`).

**Gold → `serie` (Postgres) → Metabase.** O ativo `serie_postgres` apaga e insere as
tabelas listadas em `exportar_serie.TABELAS` sem recriá-las, para preservar índices
e permissões. O Metabase lê só `serie`: com uma conexão aberta no arquivo do
DuckDB, nem o dbt nem os loaders conseguem escrever.

## Qualidade e limites atuais

- Cada fonte tem checagens de esquema, volume, meses ausentes e idempotência na
  Bronze; os comandos `just bronze-*-checar` documentam as que estão implementadas.
- O dbt executa 230 testes (2026-11-09): unicidade, não nulo, integridade
  referencial, volume e regras de negócio (por exemplo, pesos do IPCA somando 100).
- O Dagster tem *asset checks* de frescura e volume para todas as fontes que
  chegam ao DuckDB, com SLA declarado em
  [SLA e frescura](../evidencias/e3/sla_e_freshness.md), e a linhagem entre as
  camadas vem do `dagster-dbt`.
- A dimensão histórica da cesta existe no Postgres (`classificacao_versao`, migration
  `0004`) e na Gold (`dim_cesta_ipca_scd2`); ver [ADR 0001](../arquitetura.md).
- Limites: PIB do Brasil e commodities não têm fato na Gold; o clima chega à Gold
  (`fct_clima_mensal`) com buracos onde a estação do INMET parou (ver
  [carga do BDMEP](../evidencias/e3/clima_bdmep.md)); a camada semântica e o modelo preditivo são da Entrega 4.
