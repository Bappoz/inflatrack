# Componentes

## IPCA / INPC (SIDRA)

| Componente | Arquivo | Responsabilidade |
|---|---|---|
| Banco | `docker-compose.yml` | PostgreSQL 16.4; aplica `migrations/` em ordem na primeira subida |
| Esquema da referência | `migrations/0001_referencia_ipca.sql` | Cesta com vigência, localidades, variáveis e a tabela de fato `observacao` |
| Esquema transacional | `migrations/0002_lojista.sql` | `lojista`, `produto`, `reajuste` e a view `produto_preco_atual` |
| Semente | `migrations/0003_seed_referencia.sql` | 5 agregados, 11 variáveis, 17 localidades |
| Cliente da API | `src/inflatrack/sidra.py` | Requisição mensal em formato compacto, retry com backoff, leitura dos metadados |
| Carga | `src/inflatrack/ingest.py` | Grava a raw, sincroniza a cesta e insere em `observacao` |
| Verificação | `sql/verificar_carga.sql` | Volume por fonte e meses faltando |
| Comandos | `justfile` | `up`, `reset`, `seed`, `seed-amostra`, `verificar-carga`, `psql` |

## Configuração

Lida do `.env` (valores padrão entre parênteses):

| Variável | Uso |
|---|---|
| `POSTGRES_USER` (`inflatrack`) | Usuário do banco |
| `POSTGRES_PASSWORD` (`inflatrack`) | Senha |
| `POSTGRES_HOST` (`localhost`) | Host usado pela ingestão |
| `POSTGRES_PORT` (`5432`) | Porta exposta pelo Compose |
| `POSTGRES_DB` (`inflatrack`) | Nome do banco |

## Commodities

Cliente `src/inflatrack/alphavantage.py`, ingestão `ingest_commodities.py` e carga `load_commodities.py` no DuckDB; ver [Commodities e Energia](../fontes/commodities.md).
