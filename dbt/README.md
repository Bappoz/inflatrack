# dbt: como levar a sua fonte até a Silver

O dbt lê a Bronze que o **seu loader** gravou no DuckDB (`bronze.<fonte>_<tabela>`) e cria a
Silver (views em `silver`) e a Gold (tabelas em `gold`) no mesmo `data/duckdb/inflatrack.duckdb`.
Ele nunca escreve em `bronze`. Exemplos prontos: `staging/pib/`, `staging/commodities/` e
`intermediate/int_pib__mensal.sql`.

```bash
uv sync                      # instala dbt-core e dbt-duckdb
uv run python -m inflatrack.loaders.load_<fonte>   # a Bronze precisa existir antes
just dbt                     # = uv run dbt build (seeds, modelos e testes)
uv run dbt build --select +int_<fonte>__mensal     # só a sua trilha
```

`dbt_project.yml` e `profiles.yml` ficam na raiz: rode tudo a partir dela.

## O que criar (um arquivo por fonte, para não dar conflito)

| Arquivo | Conteúdo |
|---|---|
| `models/staging/<fonte>/_<fonte>__sources.yml` | A tabela `bronze.*` como `source` (modelo abaixo) |
| `models/staging/<fonte>/stg_<fonte>__<entidade>.sql` | View 1:1 com a Bronze: tipos, marcadores e nulos. **Sem `JOIN` com outra fonte** |
| `models/staging/<fonte>/_<fonte>__models.yml` | Descrição e testes da staging |
| `models/intermediate/int_<fonte>__mensal.sql` | Grão mensal: `mes_referencia` = 1º dia do mês (`DATE`), médias, variações, médias móveis e desvios |
| `models/intermediate/_int_<fonte>__models.yml` | Descrição e testes do intermediate. Um YAML por fonte, não um compartilhado |
| `seeds/seed_*.csv` (se precisar) | Catálogos fixos; declare os tipos em `seeds/_seeds.yml` |
| `tests/assert_*.sql` | Testes singulares: o que voltar da query é falha |

## O `source`, ligado ao Dagster

```yaml
version: 2

sources:
  - name: bronze_<fonte>
    schema: bronze
    tables:
      - name: <fonte>_<tabela>
        config:
          meta:
            dagster:
              asset_key: ["<fonte>_duckdb"]  # o ativo do Dagster que roda o seu loader
        columns:
          - name: <chave>
            data_tests: [not_null]
```

O `asset_key` é o nome do ativo do seu loader em `orchestration/assets/<fonte>.py` (ex.:
`pib_duckdb`, `clima_duckdb`, `salario_minimo_duckdb`). Com ele, o Dagster roda o seu modelo
depois do loader. Não é preciso escrever Python: todo modelo novo aparece sozinho no Dagster
(`orchestration/assets/dbt_assets.py`), e os testes do dbt viram *asset checks*.

## Regras que valem para todos (PLAN_E3_E4.md, Seções 1 e 6)

- Na staging você lê só `{{ source(...) }}`; daí em diante, só `{{ ref(...) }}`. Nunca escreva
  `bronze.x` ou `silver.y` direto no SQL.
- Staging e intermediate não fazem `JOIN` com a Silver de colega. As fontes se encontram na Gold,
  pela `gold.dim_calendario` (`mes_referencia`).
- Janela móvel só olha para trás: `rows between N preceding and current row`.
- Tipos (Seção 1.3): percentuais em `DECIMAL(12,4)`, códigos em `VARCHAR`, nada de `DOUBLE`/`FLOAT`
  na saída. O `stddev` e o `avg` do DuckDB devolvem `DOUBLE`: faça `cast`.
- Declare o grão no YAML ("uma linha por X x mês") e teste: chave única, `not_null` no que nunca
  pode faltar, `relationships` com os seeds e as sujeiras da sua fonte (salto, negativo, mês que
  some).
- Antes do PR: `uv run dbt build` sem erro.

## Dúvidas comuns

- **`Catalog Error: Table … does not exist`**: o loader da sua fonte ainda não rodou nesse banco.
- **O schema saiu `main_silver`**: o modelo está fora de `staging/`, `intermediate/`, `marts/` ou
  `semantic/`, ou alguém sobrescreveu o `+schema`. Quem define os schemas é o `dbt_project.yml`.
- **`database is locked` / "arquivo já está sendo usado por outro processo"**: outro processo
  (Dagster, um loader, o `dagster dev` ou um notebook) está com o arquivo aberto. O DuckDB aceita um
  escritor por vez. O Metabase nunca abre este arquivo: ele lê a cópia da Gold no Postgres.
- **Quero ver a minha tabela da Gold no painel**: ponha o nome em `TABELAS`, em
  `src/inflatrack/reverse_etl/exportar_serie.py`, e veja `scripts/sql/metabase/README.md`.
