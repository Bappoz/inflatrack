# Preços de atacadista no Postgres — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** base relacional `atacado` no Postgres com preços de um atacadista ligados ao subitem do IPCA, carregada de CSV direto no banco.

**Architecture:** migration `0007` cria o schema `atacado` (fora da publicação do CDC); um importador Python lê o CSV e grava só preços novos; nada passa por Delta, DuckDB ou dbt.

**Tech Stack:** PostgreSQL 16, psycopg 3, pytest, just.

**Spec:** `docs/superpowers/specs/2026-11-19-precos-atacadista-design.md`

## Global Constraints

- Preço de produto **nunca** em Raw/Bronze/Silver/Gold: nenhum arquivo em `dbt/`, `src/inflatrack/bronze/`, `src/inflatrack/loaders/`, `orchestration/` cita `atacado`.
- Nenhuma tabela de `atacado` em `pg_publication_tables` da publicação `inflatrack_cdc`.
- Dinheiro em centavos `integer`, como em `public.produto`.
- `atacado.preco` é insert-only, pelo trigger `impede_update_em_historico()` da 0004.
- Dado fictício sempre marcado (`fornecedor.ficticio = true`).
- Branch `feat/precos-atacadista` a partir da `origin/main`. Commits sem `Co-Authored-By`.

## Review Focus

1. Banco sem a carga do IPCA (`classificacao` vazia): o importador deve falhar antes de gravar, listando os subitens ausentes e dizendo para rodar a carga do IPCA. Teste em Task 3.
2. CSV salvo pelo Excel (UTF-8 com BOM): a primeira coluna não pode virar `﻿produto`. Teste em Task 2.
3. Reimportar o mesmo arquivo: 0 preços novos. Teste em Task 3.
4. Preço com mais de 2 casas (`7,955`): recusar, não arredondar. Teste em Task 2.
5. O mesmo produto duas vezes no CSV na mesma data com preços diferentes: recusar o arquivo inteiro. Teste em Task 3.

---

### Task 1: Migration 0007 e testes de banco

**Files:**
- Create: `migrations/0007_preco_atacadista.sql`
- Test: `tests/integration/test_atacado_schema.py`

**Interfaces:**
- Produces: `atacado.fornecedor(id, nome unique, codigo_localidade integer, ficticio boolean not null default false, criado_em)`; `atacado.produto(id, id_fornecedor fk on delete cascade, nome, unidade, codigo_subitem_ipca fk classificacao on delete restrict, criado_em, unique(id_fornecedor, nome))`; `atacado.preco(id, id_produto fk on delete cascade, preco_centavos integer check > 0, vigente_desde date, registrado_em timestamptz default now(), unique(id_produto, vigente_desde))`; view `atacado.preco_atual(id_produto, id_fornecedor, produto, unidade, codigo_subitem_ipca, preco_centavos, vigente_desde)`.

- [ ] **Step 1: testes** (fixture `pg` igual à de `test_serie_permissoes.py`, pulando sem Postgres ou sem `atacado.preco`; tudo em transação desfeita; insere `classificacao ('9999999','subitem')` on conflict do nothing):
  - `test_update_em_preco_e_barrado` → `UPDATE atacado.preco` levanta `psycopg.errors.RestrictViolation`.
  - `test_subitem_inexistente_e_recusado` → `ForeignKeyViolation`.
  - `test_preco_atual_devolve_o_mais_recente` → preços 1000 em 2026-01-01 e 1100 em 2026-02-01; a view devolve 1100.
  - `test_atacado_fora_da_publicacao_do_cdc` → `select count(*) from pg_publication_tables where pubname='inflatrack_cdc' and schemaname='atacado'` = 0.
  - `test_preco_zero_e_recusado` → `CheckViolation`.
- [ ] **Step 2:** `just migrar 0007_preco_atacadista.sql` falha (arquivo não existe) e os testes pulam/falham.
- [ ] **Step 3:** escrever a migration (`begin; ... commit;`, `if not exists`, comentários nas tabelas, índice `preco (id_produto, vigente_desde desc)`, view com `distinct on (id_produto) order by id_produto, vigente_desde desc`).
- [ ] **Step 4:** `just migrar 0007_preco_atacadista.sql` e `uv run pytest tests/integration/test_atacado_schema.py -v` → 5 passed.
- [ ] **Step 5:** commit `feat(atacado): schema relacional de preços de atacadista (migration 0007)`.

### Task 2: Conversores de formato brasileiro

**Files:**
- Create: `src/inflatrack/common/conversores.py`
- Test: `tests/unit/test_conversores.py`

**Interfaces:**
- Produces: `converter_centavos(valor: str) -> int` (aceita `R$ 1.234,56`, `12,5`, `7.95`; levanta `ValueError` em vazio, negativo ou mais de 2 casas); `converter_data(valor: str) -> date` (`%Y-%m-%d`, `%d/%m/%Y`; `ValueError` caso contrário).

Origem: `_converter_valor` e `_converter_data` do PR #21 (Artur Fernandes Galdino), trocando `float` por `Decimal`.

- [ ] **Step 1: testes**: `"R$ 1.234,56"`→123456; `"12,5"`→1250; `"7.95"`→795; `"7,955"`→ValueError; `""`→ValueError; `"-1,00"`→ValueError; `"19/11/2026"` e `"2026-11-19"` → `date(2026,11,19)`; `"2026/13/01"`→ValueError.
- [ ] **Step 2:** `uv run pytest tests/unit/test_conversores.py` → falha de import.
- [ ] **Step 3:** implementar. Ponto é separador de milhar só quando há vírgula.
- [ ] **Step 4:** testes passam.
- [ ] **Step 5:** commit `feat(common): conversores de valor e data em formato brasileiro`.

### Task 3: Importador da tabela de preços

**Files:**
- Create: `src/inflatrack/atacado/__init__.py`, `src/inflatrack/atacado/importar_tabela.py`
- Test: `tests/unit/test_importar_tabela.py`, `tests/integration/test_importar_tabela.py`

**Interfaces:**
- Consumes: `converter_centavos`, `converter_data` (Task 2); tabelas da Task 1.
- Produces:
  - `LinhaPreco` (dataclass frozen: `produto: str, unidade: str, preco_centavos: int, codigo_subitem_ipca: str, vigente_desde: date`).
  - `ler_csv(conteudo: str) -> list[LinhaPreco]`: separador `;` ou `,` pela primeira linha; tira BOM; cabeçalho exigido `produto;unidade;preco;codigo_subitem_ipca;vigente_desde`; erros com o número da linha; mesmo produto e data com preços diferentes → `ValueError`.
  - `importar(conexao, linhas, fornecedor: str, codigo_localidade: int, ficticio: bool) -> Resultado` (`Resultado(produtos_novos: int, precos_novos: int)`): numa transação; antes de gravar, confere os subitens em `classificacao` e levanta `SubitemAusente` com a lista; cria fornecedor e produto se não existirem; grava o preço só se não houver linha na mesma data e se for diferente do preço vigente naquela data.
  - `main(argv: list[str] | None = None) -> int`: `--arquivo` (obrigatório), `--fornecedor`, `--localidade` (default 5300108), `--ficticio`.

- [ ] **Step 1: testes unitários** de `ler_csv`: arquivo com BOM; separador `,`; coluna faltando → ValueError citando a coluna; preço inválido → ValueError com `linha 3`; duplicata conflitante → ValueError.
- [ ] **Step 2: testes de integração** (Postgres, transação desfeita, `classificacao` com os códigos usados): primeira importação grava N produtos e N preços; segunda importação do mesmo conteúdo → `Resultado(0, 0)`; preço alterado com data nova → 1 preço novo e `preco_atual` com o valor novo; preço igual com data nova → 0; subitem ausente → `SubitemAusente` e nenhum fornecedor gravado.
- [ ] **Step 3:** rodar e ver falhar.
- [ ] **Step 4:** implementar.
- [ ] **Step 5:** `uv run pytest tests/unit/test_importar_tabela.py tests/integration/test_importar_tabela.py -v` passam.
- [ ] **Step 6:** commit `feat(atacado): importador da tabela de preços direto no Postgres`.

### Task 4: Tabela de exemplo, receita e guarda da regra

**Files:**
- Create: `data/atacado/tabela_exemplo.csv` (~40 produtos, subitens reais da POF 2017-2018: alimentação `11*`, limpeza `2104*`, higiene `6301*`; `vigente_desde` 2026-11-01)
- Modify: `justfile` (receita `atacado-importar arquivo="data/atacado/tabela_exemplo.csv"` com `--fornecedor "Atacadista Exemplo" --ficticio`); `.gitignore` se `data/` estiver ignorado (liberar `data/atacado/`)
- Test: `tests/unit/test_regra_preco_relacional.py`

- [ ] **Step 1: testes**: `test_tabela_exemplo_e_valida` (`ler_csv` do arquivo, ≥ 35 linhas, todos os subitens com 7 dígitos); `test_preco_nao_entra_no_pipeline_analitico` (nenhum arquivo `.py/.sql/.yml` em `dbt/`, `src/inflatrack/bronze/`, `src/inflatrack/loaders/`, `orchestration/` contém `atacado`).
- [ ] **Step 2:** criar o CSV e a receita; rodar `just atacado-importar` no banco local (exige a carga do IPCA no Postgres).
- [ ] **Step 3:** testes passam; commit `feat(atacado): tabela de exemplo fictícia e receita just`.

### Task 5: Documentação

**Files:**
- Create: `docs/adr/0004-preco-produto-so-relacional.md`, `docs/dicionario/atacado.md`
- Modify: `mkdocs.yml` (nav do ADR e do dicionário), `PLAN_E3_E4.md` (camada 0 com o schema `atacado`; regra "preço de produto só no relacional"; Seção 2.4/E4: modelo prevê a variação do subitem e a recomendação lê `atacado.preco_atual`), `docs/superpowers/specs/...` (sem mudança), `AI-USAGE.md`

- [ ] **Step 1:** escrever ADR (contexto: PR #21; decisão; abordagens 1-3; consequências) e dicionário (tabelas, colunas, exemplo de consulta).
- [ ] **Step 2:** `uv run mkdocs build --strict` sem aviso.
- [ ] **Step 3:** commit `docs(atacado): ADR 0004, dicionário e plano da E4`.

### Task 6: Verificação final e PR

- [ ] `just check` (ruff + pytest) verde.
- [ ] Push da branch e PR para `main` — **pedir confirmação ao integrante antes**.
- [ ] Comentário de fechamento no PR #21 — **pedir confirmação antes**.
