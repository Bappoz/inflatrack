# Avaliação ampliada (Parte 1, ponto de parada) — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** medir, em todos os subitens do IPCA e em todas as praças, se a escolha de modelo por subitem ganha da ingênua, e parar para o integrante revisar.

**Architecture:** estender `inflatrack.predicao` para várias praças, com a praça na chave e como variável. Uma função escolhe o modelo por subitem com meses anteriores e mede o resultado em meses seguintes. Um notebook novo mostra tudo.

**Tech Stack:** pandas, numpy, xgboost, DuckDB (só leitura), Jupyter.

**Spec:** `docs/superpowers/specs/2026-11-19-aplicacao-modelo-supabase-design.md` (Parte 1)

## Global Constraints

- Candidatos: `ingenua`, `ingenua_sazonal`, `linear_tendencia`, `logaritmica_tendencia`, `xgboost_sem_clima`.
- XGBoost: um modelo único para todas as praças e subitens, com `codigo_localidade` como categoria.
- Nenhum dado de mês > t na previsão de t+1. A escolha por subitem só vê meses anteriores aos meses em que é medida.
- Não mexe nos números da avaliação anterior (`avaliacao_modelos.ipynb`): uma praça só continua igual.
- **Parar** depois da Task 3 e mostrar os números ao integrante. Nada das Partes 2 a 4.

## Review Focus

1. Defasagens e médias atravessando a fronteira entre praças do mesmo subitem: teste na Task 1.
2. A escolha por subitem medida nos mesmos meses em que foi escolhida, o que seria otimista: teste na Task 2.
3. Um par sem previsão do vencedor: a escolha cai na ingênua, como no design. Teste na Task 2.
4. Desempenho: com cerca de 4 mil séries por origem, a regressão não pode filtrar o DataFrame série a série. Usar `groupby`.
5. A avaliação anterior com uma praça continua dando os mesmos números: conferir no notebook antigo.

---

### Task 1: Base e walk-forward com várias praças

**Files:** Modify `src/inflatrack/predicao/serie.py`, `src/inflatrack/predicao/walk_forward.py`; Test `tests/unit/test_predicao_serie.py`, `tests/unit/test_predicao_walk_forward.py`

**Interfaces:**
- `montar_base(...)`: `inflacao` pode trazer `codigo_localidade`; se não trouxer, assume `1`. A chave vira `(codigo_localidade, codigo_subitem, mes)`. `FEATURES_BASE` ganha `codigo_localidade` (categoria).
- `carregar_gold(caminho, codigos: list[str] | None, codigo_localidade: int | None)`: `None` quer dizer todos.
- `avaliar(base, origens, janela=24, modelos: tuple[str, ...] = MODELOS)`: a saída ganha `codigo_localidade`.
- `metricas`: a linha comparável passa a ser `(codigo_localidade, codigo_subitem, mes_alvo)`.

- [ ] Testes: `test_lags_nao_atravessam_pracas` (duas praças do mesmo subitem; `y_lag1` do primeiro mês de cada uma é nulo); `test_avaliar_com_duas_pracas_tem_linha_por_praca`; `test_avaliar_so_roda_os_modelos_pedidos` (com `modelos=("ingenua",)`, o XGBoost não é treinado).
- [ ] Ver falhar, implementar (as regressões por `groupby` sobre o recorte), ver passar; a suíte de `test_predicao_*` continua verde.
- [ ] Commit `feat(predicao): multi-praça base and walk-forward`.

### Task 2: Escolha de modelo por subitem

**Files:** Create `src/inflatrack/predicao/escolha.py`; Test `tests/unit/test_predicao_escolha.py`

**Interfaces:**
- `escolher_por_subitem(previsoes: pd.DataFrame) -> pd.DataFrame`: uma linha por `codigo_subitem`, com `modelo` (menor MAE juntando as praças, nas linhas em que todos os candidatos previram) e `erro_tipico_pct` (esse MAE).
- `aplicar_escolha(previsoes, escolha) -> pd.DataFrame`: para cada linha `(praça, subitem, mes_alvo)`, a previsão do modelo escolhido; sem ela, a da `ingenua`. Devolve o mesmo formato de `avaliar`, com `modelo = "escolha_por_subitem"` e a coluna `modelo_usado`.
- `avaliar_escolha(previsoes, meses_escolha: int) -> pd.DataFrame`: escolhe com os primeiros `meses_escolha` meses-alvo e devolve `aplicar_escolha` só nos meses seguintes, junto dos candidatos nesses mesmos meses, para entrar em `metricas`.

- [ ] Testes: a ingênua vence quando acerta sempre; `test_escolha_nao_ve_os_meses_em_que_e_medida` (mudar `previsto` nos meses de medição não altera a escolha); a reserva cai na ingênua quando o vencedor não previu; o erro típico é o MAE à mão.
- [ ] Ver falhar, implementar, ver passar; commit `feat(predicao): per-subitem model choice with honest hold-out`.

### Task 3: Notebook e evidência, depois PARAR

**Files:** Create `notebooks/avaliacao_todas_pracas.ipynb`, `docs/evidencias/e4/avaliacao_todas_pracas.md`; Modify `mkdocs.yml`, `justfile` (`modelo-notebook` executa os dois notebooks), `src/inflatrack/predicao/exportar_graficos.py` (aceita o notebook e os nomes por parâmetro), `AI-USAGE.md`

- [ ] O notebook roda os 36 meses com os 5 candidatos em todas as praças e mostra:
  - MAE geral, por grupo e por praça;
  - quantos subitens cada modelo venceu;
  - `avaliar_escolha` com `meses_escolha=24`: a escolha por subitem contra a ingênua e contra o XGBoost fixo, nos 12 meses finais.
- [ ] A evidência traz as tabelas e um gráfico; `mkdocs build --strict` passa; teste de forma igual ao do notebook anterior.
- [ ] `just check` verde; commit `feat(predicao): evaluation across every praça and subitem`.
- [ ] **PARAR** e mostrar os números ao integrante.
