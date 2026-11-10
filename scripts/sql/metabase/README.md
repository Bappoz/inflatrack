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
garante no Postgres o usuário só-leitura do painel, cria a conexão com o Postgres
(`db:5432`), a coleção **InflaTrack (versionado)**, as perguntas e o dashboard
**InflaTrack — Painel do lojista**. Rodar de novo atualiza sem duplicar. Uma conexão já
criada à mão é reaproveitada se apontar para o mesmo banco, e passa a usar o usuário leitor.

### Com que usuário o Metabase lê o Postgres

Nunca com o dono do banco (`POSTGRES_USER`): ele enxerga `public`, onde ficam os preços de
cada loja. O script cria (ou atualiza a senha de) um login `METABASE_PG_USER`
(padrão `metabase_painel`, senha `METABASE_PG_PASSWORD`) que só tem o papel
`metabase_leitor` da migration 0005: `SELECT` em `serie` e nada mais. Quem faz isso é o script,
e não uma migration, porque a senha vem do `.env` e não pode ir para o Git.

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
| `p1_inflacao_12m_por_setor.sql` | 1. Inflação acumulada do meu setor nos últimos 12 meses | Postgres | Lê `serie.fct_inflacao_mensal` + `serie.dim_cesta_ipca_scd2` |
| `p2_sazonalidade_por_mes.sql` | 2. Sazonalidade e meses de pico da inflação | Postgres | Média por mês do ano, de jul/2006 em diante. **Falta** o efeito do clima (não chega à Gold; INMET exige token) |
| `p3_poder_de_compra_desde_2006.sql` | 3. Poder de compra desde 2006 | Postgres | Inflação pelo número-índice (1737) |
| `p3_salario_minimo_real.sql` | 3. O salário mínimo acompanhou a inflação? | Postgres | Lê `serie.fct_salario_minimo_mensal`: nominal x corrigido pelo IPCA, desde jan/2006 |
| `p4_brasil_x_regiao.sql` | 4. Brasil x praça do lojista, IPCA x INPC | Postgres | Último mês, todas as localidades |
| `p4_brasil_ipca_x_inpc_5_anos.sql` | 4. (evolução) IPCA x INPC nos últimos 5 anos | Postgres | Brasil, 60 meses |
| `p5_reajuste_minimo_por_produto.sql` | 5. Reajuste mínimo para não perder margem | Postgres | Visão interna (todas as lojas); por lojista depende do RLS da E4. A projeção (`recomendacao_reajuste`) é E4 |

A P2 e a P3 fazem um cálculo leve no próprio SQL (média por mês do ano e razão entre números-índice).
É provisório: na E4 essas métricas vão para a camada semântica do dbt (`gold.sem_*`) e as perguntas
passam só a ler o resultado.

`tests/unit/test_metabase_painel.py` falha se alguma pergunta ler fora de `serie`.

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
