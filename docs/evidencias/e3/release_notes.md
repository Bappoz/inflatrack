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

* **Clima sem medições no pipeline.** O catálogo de estações é coletado todo dia (668 estações em 2026-11-08), mas as medições diárias (`clima_medicoes`) exigem estações e intervalo por config e ficam fora do `clima_job` e do `popular_banco_job`. Em 2026-11-08 o endpoint `estacao/diaria` respondeu 404 e, logo depois, derrubou a conexão. Por isso `int_clima__anomalia_mensal` está vazia, e a P2 sai sem o efeito do clima. *Resolvido depois da release, ver [carga do BDMEP](clima_bdmep.md).*
* **Salário mínimo fora da Gold.** A Silver existe (387 meses), mas não chega a `serie`; a P3 mostra só a inflação pelo número-índice. *Resolvido depois da release, ver abaixo.*
* **Lojista fictício.** O banco do lojista nasce vazio; os dados vêm de `just simular-cdc`. A P5 mostra todas as lojas até o RLS da E4.
* **Frescura** declarada só para Dólar, Selic e `fct_macroeconomia_mensal`. *Resolvido depois da release, ver abaixo.*
* **Pendências de organização do plano:** `ingest_*`/`bronze_*` do clima e do salário mínimo ainda não foram fundidos num arquivo por fonte *(resolvido depois da release, ver abaixo)*; `tests/e2e/` ainda vazio; diários de bordo só de Lucas e Artur.

## Fechado depois da release

| Pendência | O que mudou |
|---|---|
| Salário mínimo fora da Gold | `fct_salario_minimo_mensal` (reajuste e ganho real em 12 meses, valores corrigidos pelo IPCA), copiada para `serie` (tabela acrescentada à migration `0005`; num volume que já a tinha, `just migrar 0005_serie_historica.sql`) e nova pergunta P3 no painel (`p3_salario_minimo_real.sql`) |
| Frescura só para Dólar, Selic e a macro | Checks de frescura e volume para IPCA/INPC, salário mínimo, PIB, PIB internacional, catálogo de clima e commodities; SLA por fonte em [SLA e frescura](sla_e_freshness.md) |
| `ingest_*` e `bronze_*` separados | Um arquivo por fonte: `bronze/salario_minimo.py` e `bronze/clima.py`. A linha de comando passou a ser `coletar`, `checar`, `importar` e `load` (as receitas do `justfile` e os ativos do Dagster já usam) |

Verificado em 2026-11-09, numa cópia isolada da árvore de trabalho com dados reais (Postgres e portas próprios; o IPCA, já coletado, veio do banco de desenvolvimento):

| Passo | Resultado |
|---|---|
| Jobs `macro_job`, `commodities_job`, `pib_internacional_job`, `dieese_job` e `clima_job` | SUCCESS, com os 9 checks de frescura passando dentro do Dagster |
| Coleta do PIB (2015 a 2026) e `analitico_job` | SUCCESS; `serie.fct_salario_minimo_mensal` com 387 linhas (jul/1994 a set/2026) |
| `just dbt-test` | 230 testes, 230 PASS (eram 224) |
| `pytest` com Postgres no ar | 331 passaram, 0 pulados |
| `just metabase-painel` | 7 perguntas criadas (eram 6) |

O Parquet e o HTML legados que a coleta do salário mínimo ainda grava em `data/parquet/dieese/` e `data/raw/dieese/` foram **mantidos** de propósito (decisão de 2026-11-09): o loader do DuckDB os usa para as tabelas da E1. O prazo de 75 dias do SLA de IPCA/INPC e do salário mínimo também foi confirmado (ver [SLA e frescura](sla_e_freshness.md#5-decisoes-registradas)).

Continuam abertos os diários de bordo que faltam. As medições do clima entraram no pipeline em seguida, pelos pacotes anuais do BDMEP, até a nova `gold.fct_clima_mensal` (ver [carga do BDMEP](clima_bdmep.md)).

### Cobertura ponta a ponta (`tests/e2e/`)

`tests/e2e/` estava vazio. Agora `test_cadeia_salario_minimo.py` roda a cadeia do salário mínimo com o código real: HTML da fixture, Bronze Delta, loader, `dbt build` (modelos e testes) em subprocesso, cópia para o Postgres e a consulta da P3 do painel. Só o IPCA é sintético, com um índice conhecido, para conferir o resultado do dbt contra uma conta feita em Python. Quebrar de propósito as fórmulas do modelo derrubou os testes de reajuste e de valor corrigido.

| Regra do Nível 5 do plano | Situação |
|---|---|
| Mesma métrica, mesmo valor (DuckDB, `serie` e painel) | Coberta para o salário mínimo: Gold, cópia no Postgres e consulta do painel dão as mesmas linhas. Falta para as demais métricas |
| Isolamento entre lojista e dados oficiais | Só por linhagem (`tests/orchestration/test_ipca_transacional.py`) e pelo teste dbt `assert_fct_inflacao_sem_vazamento_de_lojista`. Não há E2E que altere um preço no Postgres do lojista e confira as tabelas oficiais |
| Validação *walk-forward* do modelo | E4 (o modelo ainda não existe) |
| ETL reverso e controle de acesso por lojista (RLS) | E4 |

Também não há E2E do IPCA (da coleta à Gold), do CDC até a Gold nem de um job do Dagster. Esses caminhos só foram exercitados na execução do zero de 2026-11-08 e na de 2026-11-09, feitas à mão.

## Fica para a E4

RLS por lojista e privilégio mínimo, ETL reverso da recomendação de reajuste, camada semântica
das métricas no dbt, modelo preditivo, de-para produto × subitem, catálogo, linhagem e LGPD.
