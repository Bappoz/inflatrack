# Avaliação dos modelos de previsão do subitem — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** comparar, em walk-forward, seis previsões da variação mensal do subitem do IPCA em t+1 (2 ingênuas, regressão linear, regressão logarítmica, XGBoost sem e com clima) e mostrar o resultado num notebook.

**Architecture:** funções puras e testadas em `src/inflatrack/predicao/` (montar a base sem vazamento, os modelos, o walk-forward e as métricas); o notebook só lê a Gold, chama as funções e desenha. Nada é gravado em banco.

**Tech Stack:** pandas, numpy, xgboost, DuckDB (só leitura), matplotlib, Jupyter/nbconvert.

**Spec:** `docs/superpowers/specs/2026-11-19-avaliacao-modelos-design.md`

## Global Constraints

- Praça da avaliação: Brasil, `codigo_localidade = 1`, como parâmetro (não constante enterrada).
- Alvo: `gold.fct_inflacao_mensal.variacao_mensal_pct`, `indice = 'IPCA'`, do mês t+1.
- Nenhuma variável de mês > t na linha que prevê t+1; nada ajustado com a série inteira.
- Regressões sobre os últimos **24** meses do índice encadeado (`t = 1..24`, projeta `t = 25`).
- Teste: os últimos **36** meses-alvo com IPCA divulgado; janela de treino expansível.
- XGBoost: `max_depth=4`, `n_estimators=300`, `learning_rate=0.05`, `random_state=42`, `tree_method="hist"`, `enable_categorical=True`.
- Não ler `atacado.preco`; do Postgres só `atacado.produto.codigo_subitem_ipca`.
- Commits sem `Co-Authored-By`. Branch `feat/modelo-reajuste`.

## Review Focus

1. Subitem com buraco (`variacao_mensal_pct` nulo) dentro da janela de 24 meses: a regressão devolve `nan`, e as métricas comparam só as linhas em que todos os modelos previram. Teste na Task 3.
2. ENSO publicado com atraso de 2 meses: a linha de t usa o ENSO mais recente com `mes_publicacao <= t`, nunca o de `mes_referencia = t`. Teste na Task 1.
3. Clima de polo em mês não fechado (`mes_fechado = false`): fica nulo, não entra parcial. Teste na Task 1.
4. Subitem que começa no meio do período de teste (como o macarrão instantâneo, `1102061`, que começa em 2020 em Brasília): não quebra o walk-forward, só tem menos linhas. Teste na Task 3.
5. Postgres fora do ar: a lista de subitens cai para `data/atacado/tabela_exemplo.csv`. Teste na Task 1.

---

### Task 1: Base sem vazamento

**Files:**
- Create: `src/inflatrack/predicao/__init__.py`, `src/inflatrack/predicao/serie.py`
- Test: `tests/unit/test_predicao_serie.py`

**Interfaces:**
- Produces:
  - `GRUPO_CLIMA: dict[str, tuple[str, ...]]`: subitem → polos (Regra 5). Hortaliças `1103003`, `1103043`, `1103028`, `1103044` → Itapeva, Irecê, Ituporanga; arroz `1101002` → Alegrete; feijão `1101073`, `1101052` → Unaí, Irecê; café `1114022` → Varginha, Patrocínio, Linhares; leite `1111004`, `1111009`, `1111011`, `1111031` → Juiz de Fora; óleo e carnes `1113013`, `1107095`, `1107018`, `1110009` → Sorriso, Rio Verde, Dourados, Passo Fundo, Barreiras.
  - `montar_base(inflacao, enso, polos, macro) -> pd.DataFrame`: uma linha por `(codigo_subitem, mes)`, com `y` (variação de `mes`), `alvo` (variação de `mes + 1`), `mes_alvo`, as variáveis `FEATURES_BASE` e `FEATURES_CLIMA`, e `grupo` (2 primeiros dígitos).
  - `FEATURES_BASE: list[str]`: `y`, `y_lag1`, `y_lag2`, `media_3m`, `media_6m`, `media_12m`, `desvio_12m`, `mes_do_ano_alvo`, `codigo_subitem` (categoria), `grupo` (categoria), `dolar_var_mensal_pct`, `selic_acumulada_mes_pct`.
  - `FEATURES_CLIMA: list[str]`: `el_nino`, `la_nina`, `el_nino_t3`, `la_nina_t3`, `el_nino_t6`, `la_nina_t6`, `el_nino_t9`, `la_nina_t9`, `el_nino_t12`, `la_nina_t12`, `temp_anomalia_polos`, `spi3_polos`.
  - `carregar_gold(caminho_duckdb: Path, codigos: list[str], codigo_localidade: int) -> pd.DataFrame`: lê as 4 fatos (DuckDB `read_only=True`) e chama `montar_base`.
  - `subitens_do_atacado(dsn: str | None = None) -> list[str]`: lê `select distinct codigo_subitem_ipca from atacado.produto`; com `psycopg.OperationalError`, lê o CSV de exemplo.

- [ ] **Step 1: testes** (DataFrames sintéticos pequenos):
  - `test_alvo_e_o_mes_seguinte`: `alvo` da linha de jan é o `y` de fev.
  - `test_nenhuma_variavel_vem_do_futuro`: série com sentinela 999 em todos os meses > t; a linha de t não tem 999 em nenhuma coluna de feature.
  - `test_enso_respeita_a_publicacao`: ENSO de `mes_referencia = mar` com `mes_publicacao = mai`; a linha de abr usa o ENSO de fev, não o de mar.
  - `test_clima_de_mes_nao_fechado_fica_nulo`.
  - `test_subitem_fora_da_regra_5_nao_tem_clima_de_polo` (açúcar `1104003` → `temp_anomalia_polos` nulo).
  - `test_subitens_caem_para_o_csv_sem_postgres` (DSN para porta fechada → 45 códigos do CSV).
- [ ] **Step 2:** `uv run pytest tests/unit/test_predicao_serie.py -q` → erro de import.
- [ ] **Step 3:** implementar. Médias, desvio e lags via `groupby(...).rolling/shift` só sobre `y` até t. ENSO por `pd.merge_asof` em `mes_publicacao` (`direction="backward"`). Polos: média de `temp_media_anomalia` e `spi_3` só nas linhas com `mes_fechado`.
- [ ] **Step 4:** testes passam.
- [ ] **Step 5:** commit `feat(predicao): leakage-free feature table from the Gold`.

### Task 2: Modelos

**Files:**
- Create: `src/inflatrack/predicao/modelos.py`
- Modify: `pyproject.toml` (`xgboost` em `dependencies`; `matplotlib`, `jupyter`, `nbconvert` no grupo `dev`), `uv.lock`
- Test: `tests/unit/test_predicao_modelos.py`

**Interfaces:**
- Produces:
  - `indice_encadeado(variacoes_pct: np.ndarray) -> np.ndarray` (base 100; `nan` propaga).
  - `prever_linear(indice: np.ndarray) -> float` e `prever_logaritmica(indice: np.ndarray) -> float`: ajustam `a + b·t` e `a + b·ln(t)`, `t = 1..len`, e devolvem a variação prevista em % para `t = len+1`; `nan` se houver `nan` no índice.
  - `treinar_xgboost(treino: pd.DataFrame, colunas: list[str]) -> xgboost.XGBRegressor` e `prever_xgboost(modelo, linhas, colunas) -> np.ndarray`.

- [ ] **Step 1: testes**: índice de `[1.0, 2.0]` → `[101.0, 103.02]`; série `10 + 2t` → linear prevê exatamente `(10+2·25)/(10+2·24) − 1` em %; série `5 + 3·ln(t)` → logarítmica idem; janela com `nan` → `nan`; XGBoost numa relação `alvo = 2·x` com 200 linhas tem MAE de treino < 0,5 e é determinístico (duas execuções iguais).
- [ ] **Step 2:** ver falhar; `uv add xgboost`, `uv add --group dev matplotlib jupyter nbconvert`.
- [ ] **Step 3:** implementar com `numpy.polyfit`.
- [ ] **Step 4:** testes passam.
- [ ] **Step 5:** commit `feat(predicao): linear and log regression baselines and XGBoost wrappers`.

### Task 3: Walk-forward e métricas

**Files:**
- Create: `src/inflatrack/predicao/walk_forward.py`
- Test: `tests/unit/test_predicao_walk_forward.py`

**Interfaces:**
- Consumes: `montar_base` (Task 1), funções da Task 2.
- Produces:
  - `MODELOS = ("ingenua", "ingenua_sazonal", "linear", "logaritmica", "xgboost_sem_clima", "xgboost_com_clima")`.
  - `origens_de_teste(base: pd.DataFrame, meses: int = 36) -> list[pd.Timestamp]`: os últimos `meses` valores de `mes` cujo `alvo` não é nulo.
  - `avaliar(base, origens, janela=24) -> pd.DataFrame` com colunas `codigo_subitem, grupo, mes, mes_alvo, modelo, previsto, real`. Na origem t, o XGBoost treina só com linhas de `mes <= t − 1` (o alvo delas, `mes + 1`, já era conhecido em t); `ingenua` = `y`; `ingenua_sazonal` = `y` de `mes_alvo − 12`; as regressões usam o índice dos últimos `janela` meses até t.
  - `metricas(previsoes, por: list[str] | None = None) -> pd.DataFrame`: `mae`, `rmse`, `ganho_sobre_ingenua`, `n`; só nas linhas `(codigo_subitem, mes_alvo)` em que todos os modelos têm `previsto` não nulo.

- [ ] **Step 1: testes**: `test_xgboost_so_treina_com_alvos_ja_conhecidos` (espiona `treinar_xgboost`; em cada origem, `max(treino.mes) <= origem − 1 mês`); `test_metricas_contra_conta_a_mao` (MAE e RMSE de 3 pontos); `test_metricas_comparam_as_mesmas_linhas` (um modelo com `nan` numa linha tira essa linha de todos); `test_subitem_que_comeca_tarde_nao_quebra` (subitem com 30 meses entra só onde tem janela); `test_ganho_da_ingenua_e_zero`.
- [ ] **Step 2:** ver falhar.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** testes passam; commit `feat(predicao): walk-forward evaluation and metrics`.

### Task 4: Notebook, receita e evidência

**Files:**
- Create: `notebooks/avaliacao_modelos.ipynb` (executado, com saídas), `docs/evidencias/e4/avaliacao_modelos.md`
- Modify: `justfile` (receita `modelo-notebook`: `uv run jupyter nbconvert --to notebook --execute --inplace notebooks/avaliacao_modelos.ipynb`), `mkdocs.yml` (evidência na nav, se a pasta e4 estiver lá), `AI-USAGE.md`
- Test: `tests/unit/test_predicao_notebook.py`

- [ ] **Step 1: teste** `test_notebook_so_usa_o_pacote` (o JSON do notebook importa de `inflatrack.predicao`, não define `def ` de modelo em célula, e não cita `atacado.preco`).
- [ ] **Step 2:** escrever o notebook: contexto curto; carga (`subitens_do_atacado`, `carregar_gold(..., codigo_localidade=1)`); `avaliar`; tabela geral, por grupo e top/bottom subitens; gráficos de previsto contra real (geral e 4 subitens: arroz, feijão, café, tomate); conclusão escrita a partir dos números.
- [ ] **Step 3:** `just modelo-notebook` roda sem erro; teste passa.
- [ ] **Step 4:** evidência com a tabela final e a conclusão; `mkdocs build --strict`.
- [ ] **Step 5:** commit `feat(predicao): evaluation notebook comparing the six models`.

### Task 5: Verificação final

- [ ] `just check` verde.
- [ ] Revisão independente da branch; correções com teste.
- [ ] Push e PR empilhado (base `feat/precos-atacadista`): pedir confirmação ao integrante.
