# Evidência E3 — Dagster: retry, backfill e queda de dependência

Executado em **2026-10-30** na máquina de desenvolvimento (Windows 11, Dagster 1.13.26, dagster-dbt 0.29.26, dbt-duckdb 1.11.1, DuckDB 1.5.5). Trilha usada: PIB setorial (SIDRA 1846).

!!! info "Onde está o código"
    [`orchestration/assets/pib.py`](https://github.com/Bappoz/inflatrack/blob/main/orchestration/assets/pib.py) define a coleta particionada por ano e a carga no DuckDB. [`orchestration/assets/dbt_assets.py`](https://github.com/Bappoz/inflatrack/blob/main/orchestration/assets/dbt_assets.py) coloca os modelos do dbt no grafo, e [`orchestration/partitions.py`](https://github.com/Bappoz/inflatrack/blob/main/orchestration/partitions.py) tem a partição `PIB_ANUAL`. Testes em `tests/orchestration/test_pib_backfill.py` e `tests/orchestration/test_dbt_e_retry.py`.

## O grafo

```text
pib_parquet (SIDRA -> Delta, partição por ano, retry)
   -> pib_duckdb (Delta -> bronze.pib_valor, pool duckdb_writer)
      -> silver/stg_pib__valor -> silver/int_pib__mensal   (dbt, pool duckdb_writer)
```

A ligação `pib_duckdb -> stg_pib__valor` vem do `meta.dagster.asset_key` da source no dbt. Os testes do dbt aparecem no Dagster como *asset checks*.

## 1. Retry quando a API cai

Falha de rede usa a política `RETRY_REDE`: 2 retentativas, com 30 s de espera e recuo exponencial. O ingestor do PIB captura o erro HTTP e sai com código 1; o ativo transforma isso em `Failure`, que o Dagster tenta de novo.

O teste `test_dagster_tenta_de_novo_quando_o_sidra_devolve_503` roda o ingestor real contra um SIDRA falso que devolve **HTTP 503** no primeiro pedido e as respostas reais gravadas em `tests/fixtures/pib/` depois:

| O que o teste confirma | Resultado |
|---|---|
| Eventos `STEP_UP_FOR_RETRY` | 1 |
| Pedidos de metadados ao SIDRA | 2 (o 1º com 503) |
| Execução | sucesso na 2ª tentativa |
| Linhas na Bronze (Delta) | 46 (2 trimestres de 2026 x 23 setores) |

As commodities ficam **sem retry** de propósito: a Alpha Vantage tem cota de 25 requisições por dia, e cada coleta gasta 9 delas.

## 2. Backfill de anos passados

O PIB é particionado por ano (de 1996 ao ano corrente). O ingestor já faz uma requisição por ano, então particionar não aumenta as chamadas. Com `BackfillPolicy.single_run`, um intervalo de anos vira uma execução só.

```bash
dagster asset materialize -m orchestration.definitions --select pib_parquet --partition-range "2025...2026"
dagster asset materialize -m orchestration.definitions --select pib_duckdb
```

| Medida | Valor |
|---|---|
| Execuções criadas | 1 (`ingest_pib --de 2025 --ate 2026`) |
| Linhas lidas do SIDRA | 138 (92 de 2025 e 46 de 2026) |
| Respostas novas na Bronze | 0 de 2 |
| Linhas novas em `pib_valor` (Delta) | 0 de 138 |
| Linhas novas em `bronze.pib_valor` (DuckDB) | 0, total segue em 2.806 |

O IBGE não revisou nada entre a coleta de 28/10 e o backfill, então nada novo entrou. Se houvesse revisão, ela entraria como **linha nova**, sem apagar a anterior, e a Silver passaria a mostrar a versão mais recente. A Silver e a Gold não precisam de backfill: a Silver é view, e a Gold é reconstruída a cada `dbt build`.

O agendamento `pib_job_divulgacao` relê o ano corrente e o anterior todos os dias nos meses de divulgação (março, junho, setembro e dezembro).

## 3. Queda de uma dependência, de propósito

A pasta do Delta do PIB foi **movida** (não apagada) para tirar a fonte do ar, e o loader foi rodado com tudo o que depende dele (`--select "pib_duckdb*"`).

| Momento | O que aconteceu |
|---|---|
| Antes | `data/parquet/pib/` com 97 arquivos (hash SHA-256 de cada um registrado); `bronze.pib_valor` com 2.806 linhas; `silver.int_pib__mensal` com 8.510 |
| Fonte fora do ar (run `d59eda52`) | `pib_duckdb`: `STEP_FAILURE` ("Tabela Delta do PIB não encontrada"). `dbt_inflatrack`: **"Dependencies for step dbt_inflatrack failed: ['pib_duckdb']. Not executing."** A execução terminou em `RUN_FAILURE` |
| Dados durante a falha | `bronze.pib_valor` com 2.806 e `silver.int_pib__mensal` com 8.510: nada foi apagado nem recalculado sobre dado faltando |
| Fonte de volta | Pasta restaurada; os hashes dos 97 arquivos são idênticos aos de antes |
| Retomada (run `8e9533d0`) | `pib_duckdb`: `STEP_SUCCESS`, 0 linhas novas. `dbt_inflatrack`: `stg_pib__valor` e `int_pib__mensal` materializados e 8 asset checks aprovados, inclusive `assert_pib_sem_vazamento_futuro`. A execução terminou em `RUN_SUCCESS` |

O que isso garante: quando uma etapa falha, as camadas de baixo não rodam em cima de dado incompleto e continuam servindo a última versão boa. A volta é só rodar de novo, porque cada etapa é idempotente.

## Como reproduzir

```bash
uv run pytest tests/orchestration          # retry, backfill, grafo e agendamento (nível 4)
just orquestrador                          # interface em http://localhost:3000
```
