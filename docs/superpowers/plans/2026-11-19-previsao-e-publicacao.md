# Previsão na Gold e publicação no Supabase (Partes 2 a 4) — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** prever, todo mês, a variação de cada subitem em cada praça com o XGBoost fixo, e publicar o mínimo no Supabase para o site e o agente.

**Architecture:**
- Funções puras em `inflatrack.predicao.aplicacao`, chamadas por um modelo Python do dbt (`gold.fct_previsao_subitem`, grupo `predicao`).
- `inflatrack.reverse_etl.publicar_site` coleta a previsão, os nomes e o resumo do DuckDB (só leitura) e os gráficos do painel da `serie` local, e grava tudo no Supabase numa transação.
- `predicao_job` mensal no Dagster.

**Tech Stack:** pandas, xgboost, dbt-duckdb (Python model), psycopg, Dagster.

**Spec:** `docs/superpowers/specs/2026-11-19-aplicacao-modelo-supabase-design.md` (Partes 2 a 4)

## Global Constraints

- XGBoost sem clima, `FEATURES_BASE`, parâmetros de `modelos.PARAMETROS_XGBOOST`.
- Treino só com linhas de mês <= `mes_base` − 1 que têm alvo; o erro típico vem dos 12 meses até `mes_base`.
- O Supabase nunca recebe preço nem dado de usuário. `SUPABASE_DB_URL` só no `.env`; o `.env.example` leva o campo vazio.
- Retenção: cada publicação apaga e reescreve as 5 tabelas numa transação só.
- `fct_previsao_subitem` fora do `analitico_job` e sem automação `eager`.

## Review Focus

1. Uma publicação que falha no meio não pode deixar o site sem dado: tudo numa transação. Teste na Task 3.
2. `SUPABASE_DB_URL` ausente: o ativo falha com mensagem clara e sem retry. Teste na Task 4.
3. Uma série sem IPCA em `mes_base` (praça que parou de medir o subitem): sem previsão. Teste na Task 1.
4. Um subitem sem previsão na janela do erro (série curta): recebe o MAE do grupo. Teste na Task 1.
5. Ler o DuckDB enquanto o dbt escreve: o ativo de publicação entra no pool `duckdb_writer`.

---

### Task 1: Previsão e erro típico

**Files:** Create `src/inflatrack/predicao/aplicacao.py`; Test `tests/unit/test_predicao_aplicacao.py`

**Interfaces:**
- Produces:
  - `prever_proximo_mes(base: pd.DataFrame) -> pd.DataFrame`, com as colunas `codigo_localidade, codigo_subitem, mes_base, mes_previsto, variacao_prevista_pct`.
  - `erro_tipico(base: pd.DataFrame, meses: int = 12) -> pd.DataFrame`, com as colunas `codigo_subitem, erro_tipico_pct`.
  - `tabela_previsao(base, gerado_em: pd.Timestamp) -> pd.DataFrame`, que junta as duas e acrescenta `gerado_em`.

- [ ] Testes:
  - o mês previsto é `mes_base + 1`;
  - o treino só vê `mes <= mes_base − 1` (espiar `treinar_xgboost`);
  - uma série sem `y` em `mes_base` fica fora;
  - um subitem sem previsão na janela recebe o MAE do grupo;
  - a chave é única.
- [ ] Ver falhar, implementar (o erro usa `avaliar(..., modelos=("xgboost_sem_clima",))` + `metricas(por=["codigo_subitem"])`), ver passar e fazer o commit.

### Task 2: Modelo do dbt e grupo no Dagster

**Files:**
- Create: `dbt/models/predicao/fct_previsao_subitem.py`, `dbt/models/predicao/_predicao__models.yml`
- Modify: `dbt_project.yml` (pasta `predicao` → schema `gold`), `orchestration/assets/dbt_assets.py` (`predicao` → grupo `predicao`, sem `eager`)
- Test: `tests/orchestration/test_predicao.py`

- [ ] Testes:
  - o ativo `fct_previsao_subitem` está no grupo `predicao`;
  - ele não tem condição de automação;
  - o `analitico_job` não o seleciona.
- [ ] Implementar. O modelo lê `dbt.ref` das 4 fatos e chama `montar_base` e `tabela_previsao`. Testes do yml: chave única, campos não nulos e `erro_tipico_pct >= 0`.
- [ ] Rodar `uv run dbt build --select fct_previsao_subitem` no DuckDB local: cerca de 4 mil linhas e os testes passando. Fazer o commit.

### Task 3: Esquema do Supabase e publicação

**Files:**
- Create: `web/backend/migrations/003_publicacao_inflatrack.sql`, `src/inflatrack/reverse_etl/publicar_site.py`
- Test: `tests/integration/test_publicar_site.py`, `tests/unit/test_publicar_site.py`

**Interfaces:**
- `UF_PRACA: dict[str, int]`, com as 27 UFs.
- `Publicacao` (dataclass): `previsao`, `subitem`, `uf_praca`, `resumo` (DataFrames) e `painel` (lista de `(id, titulo, linhas: list[dict], ate_o_mes)`).
- `coletar(caminho_duckdb: Path, dsn_local: str) -> Publicacao`.
- `gravar(conexao: psycopg.Connection, publicacao: Publicacao) -> dict[str, int]`, que apaga e insere numa transação e devolve as linhas por tabela.
- `main(argv=None) -> int`.

- [ ] Testes unitários:
  - `UF_PRACA` tem 27 UFs e só códigos de praça existentes;
  - o `jsonb` do painel converte data e Decimal.
- [ ] Testes de integração, numa transação desfeita no Postgres local, num schema temporário, com os papéis `anon` e `authenticated` criados dentro da transação:
  - a migration cria as tabelas;
  - publicar duas vezes não dobra as linhas;
  - um erro no meio mantém a publicação anterior;
  - `anon` lê e não escreve.
- [ ] Implementar e fazer o commit.

### Task 4: Job, receita e documentação

**Files:**
- Create: `orchestration/assets/site.py`
- Modify: `orchestration/schedules.py`, `.env.example`, `justfile` (`publicar-site`), `docs/pipeline/orquestracao.md`, `AI-USAGE.md`
- Test: `tests/orchestration/test_predicao.py`

- [ ] Testes:
  - `predicao_job` roda `fct_previsao_subitem` e `site_supabase`;
  - tem agendamento `0 11 14 * *`;
  - `site_supabase` está no pool `duckdb_writer` e não tem dependentes;
  - sem `SUPABASE_DB_URL`, falha sem retry.
- [ ] Implementar. `just check` verde. Rodar a previsão de verdade. Fazer o commit.
- [ ] Revisão independente da branch; correções com teste.
