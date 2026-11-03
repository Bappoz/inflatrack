# Painel do Metabase versionado

O que se cria na interface do Metabase (pergunta, gráfico, dashboard) fica no banco interno
dele, não no Git, e exportar isso em arquivo só existe nos planos pagos. Por isso **o painel
mora nesta pasta** e é recriado por um script:

| Arquivo | O que é |
|---|---|
| `painel.toml` | O dashboard: nome, conexões e, para cada pergunta, título, gráfico, eixos e posição |
| `p<N>_*.sql` | Uma consulta por pergunta. O cabeçalho diz de onde ela lê e o que é provisório |
| `../../metabase_painel.py` | Lê esta pasta e cria ou atualiza tudo no Metabase pela API |

## Subir o painel do zero

```bash
# no .env: METABASE_EMAIL e METABASE_SENHA (ver .env.example)
docker compose --profile bi up -d     # Metabase em http://localhost:3001
just metabase-painel                  # = uv run python scripts/metabase_painel.py
```

O script faz a configuração inicial do Metabase com esse login (se ainda não foi feita),
cria a conexão com o Postgres (`db:5432`), a coleção **InflaTrack (versionado)**, as
perguntas e o dashboard **InflaTrack — Painel do lojista**. Rodar de novo atualiza sem
duplicar. Uma conexão já criada à mão é reaproveitada se apontar para o mesmo banco.

## Mudar ou criar uma pergunta

1. Escreva ou altere o `.sql`. Teste a consulta direto no banco antes.
2. Declare a pergunta em `painel.toml` (bloco `[[perguntas]]`).
3. Rode `just metabase-painel` e confira no navegador.
4. Commite o `.sql` e o `painel.toml`.

**Não edite as perguntas da coleção versionada pela interface:** a próxima sincronização
sobrescreve. Para rascunhos, use outra coleção.

## Perguntas

| Arquivo | Pergunta do projeto | Banco | Situação |
|---|---|---|---|
| `p1_inflacao_12m_por_setor.sql` | 1. Inflação acumulada do meu setor nos últimos 12 meses | Postgres | **Provisória:** lê o IPCA do Postgres até a `gold.fct_inflacao_mensal` existir |

A `gold.fct_inflacao_mensal` já existe e é copiada para `serie.fct_inflacao_mensal`. A troca da
pergunta 1 para ler de lá (filtrando `indice = 'IPCA'`) está pendente.

## De onde o painel lê: só do Postgres

```
dbt (Gold no DuckDB) -> ativo serie_postgres -> Postgres, schema serie -> Metabase
```

O Metabase **nunca** se conecta ao arquivo do DuckDB: com uma conexão dele aberta, mesmo
somente leitura, o dbt e os loaders não conseguem escrever ("arquivo já está sendo usado por
outro processo", testado em 30/10/2026). Por isso o contêiner do Metabase nem monta a pasta
`data/duckdb`, e o script recusa conexão com DuckDB.

Para uma tabela da Gold aparecer no painel:
1. acrescente o nome dela em `TABELAS`, em `src/inflatrack/reverse_etl/exportar_serie.py`;
2. rode `uv run python -m inflatrack.reverse_etl.exportar_serie` (no Dagster, o ativo
   `serie_postgres` faz isso sozinho depois do dbt);
3. escreva a pergunta lendo `serie.<tabela>`.
