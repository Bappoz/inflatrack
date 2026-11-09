# Release Notes — Entrega 3

A Entrega 3 leva cada fonte da Bronze até a Silver mensal, monta a Gold com SCD tipo 2, copia
a Gold para o schema `serie` do Postgres e publica o primeiro painel do Metabase, tudo
orquestrado pelo Dagster. O plano de origem é a Seção 5 do `PLAN_E3_E4.md`.

## O que entrou

| Frente | Entrega | Onde | PR |
|---|---|---|---|
| IPCA/INPC e lojista (Lucas) | Fusão da coleta em `bronze/ipca.py`; CDC lógico (`pgoutput`) do banco do lojista sem CNPJ; Silver mensal; SCD2 da cesta e do preço/custo; `fct_inflacao_mensal` e `fct_reajuste_lojista`; vitrine `serie` (migration `0005`) e EXPLAIN com e sem índice | [evidência](ipca_lojista.md), [EXPLAIN](explain_serie.md), [ADR CDC × lote](../../adr/cdc-vs-lote.md) | #13 |
| PIB internacional (Artur) | Cliente único do Banco Mundial, Bronze unificada de China, EUA e Rússia, loader, `fct_pib_internacional_anual` e diário de bordo | [diário](../../diario/artur.md) | #14 |
| Clima e salário mínimo (Johnnatan) | Correção do `0.0 °C`, Bronze de medições do INMET, de-para estação → localidade (`seed_de_para_estacao_localidade`), Silver mensal do clima com defasagens de 1, 2 e 3 meses e Silver mensal do salário mínimo | `int_clima__anomalia_mensal`, `int_salario_minimo__mensal` | #15 |
| Dólar e Selic (Pedro) | Silver mensal (média, fechamento, variação, médias móveis de 3, 6 e 12 meses, desvio), Gold câmbio × juros (`fct_macroeconomia_mensal`), *asset checks* de frescura e SLA declarado | [SLA e frescura](sla_e_freshness.md) | #16 |
| PIB, commodities, Dagster e painel (João Pedro) | Bronze do PIB e das commodities num ponto único de entrada, só em Delta; backfill que pula o período não divulgado; `popular_banco_job` para a primeira carga; painel do Metabase com as 5 perguntas, lendo só `serie` com usuário só-leitura | [orquestração](../../pipeline/orquestracao.md), `scripts/sql/metabase/` | branch `E3-pipeline` |

## Correções feitas na integração

Encontradas ao rodar a E3 do zero num clone limpo (2026-11-08):

| Problema | Efeito | Correção |
|---|---|---|
| `pib_duckdb` no mesmo job que `pib_parquet`, que só materializa os anos publicados (`output_required=False`) | O Dagster pulava a carga, `bronze.pib_valor` não existia e o `dbt build` do `analitico_job` falhava | A carga do PIB passou para o `analitico_job`, como a do IPCA. Teste que impede o caso em qualquer job |
| `transacional_job` disparado junto com a carga completa do IPCA no `popular_banco_job` | Mais de 2 GB de WAL sem leitura do slot: o Postgres invalidou o slot do CDC (`max_slot_wal_keep_size`) | O CDC espera as três coletas do SIDRA |
| Healthcheck do Postgres pelo socket | `just up` devolvia "healthy" durante as migrations de init | `pg_isready -h 127.0.0.1` |
| `target/manifest.json` velho | Testes do Dagster quebravam depois de um pull que mudou `.yml` do dbt | `just test` roda `dbt parse` antes |

## Verificação do zero (clone limpo, 2026-11-08)

Postgres novo com as migrations `0001..0005`, Dagster local e o `.env` do grupo.

| Passo | Resultado |
|---|---|
| `popular_banco_job` | 10 jobs de fonte em SUCCESS, 32,8 min no total (`ipca_job` 30,5 min) |
| Partições do SIDRA | IPCA 243 (jul/2006 a set/2026), INPC 81, número-índice 562; out/2026 ainda não divulgado, pendente |
| `just simular-cdc` + `transacional_job` + `analitico_job` | SUCCESS; `dbt build` e cópia para `serie` |
| `serie` no Postgres | `fct_inflacao_mensal` 1.662.314 linhas (dez/1979 a set/2026), `fct_macroeconomia_mensal` 83, `dim_cesta_ipca_scd2` 1.834, `fct_reajuste_lojista` 45 |
| `just metabase-painel` | 6 perguntas criadas; todas executadas pela API com o usuário `metabase_painel`, todas com linhas |
| `just check` | ruff sem erro; pytest 306 passaram, 0 pulados (Postgres no ar) |
| `just dbt-test` | 224 testes, 224 PASS |
| `just docs-build` | `mkdocs build --strict` sem erro |

## Limitações conhecidas

* **Clima sem medições no pipeline.** O catálogo de estações é coletado todo dia (668 estações em 2026-11-08), mas as medições diárias (`clima_medicoes`) exigem estações e intervalo por config e ficam fora do `clima_job` e do `popular_banco_job`. Em 2026-11-08 o endpoint `estacao/diaria` respondeu 404 e, logo depois, derrubou a conexão. Por isso `int_clima__anomalia_mensal` está vazia, e a P2 sai sem o efeito do clima.
* **Salário mínimo fora da Gold.** A Silver existe (387 meses), mas não chega a `serie`; a P3 mostra só a inflação pelo número-índice.
* **Lojista fictício.** O banco do lojista nasce vazio; os dados vêm de `just simular-cdc`. A P5 mostra todas as lojas até o RLS da E4.
* **Frescura** declarada só para Dólar, Selic e `fct_macroeconomia_mensal`.
* **Pendências de organização do plano:** `ingest_*`/`bronze_*` do clima e do salário mínimo ainda não foram fundidos num arquivo por fonte; `tests/e2e/` ainda vazio; diários de bordo só de Lucas e Artur.

## Fica para a E4

RLS por lojista e privilégio mínimo, ETL reverso da recomendação de reajuste, camada semântica
das métricas no dbt, modelo preditivo, de-para produto × subitem, catálogo, linhagem e LGPD.
