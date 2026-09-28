# Componentes

Esta página descreve as peças do sistema por **papel**, não por fonte. Toda fonte nova entra encaixando-se nos mesmos papéis; a trilha de camadas que essas peças percorrem está em [Arquitetura Medallion](arquiteturaMedallion.md), e o que cada origem tem de particular fica na sua página em [Fonte Dados](fonteDados.md).

## Anatomia de uma fonte

Cada origem é atendida por até três módulos em `src/inflatrack/`, com uma responsabilidade só cada um:

| Papel | Convenção de nome | Responsabilidade | O que não faz |
|---|---|---|---|
| **Cliente da origem** | `<origem>.py` (ex.: `sidra.py`, `dieese.py`, `inmet.py`) | Falar com uma origem só: URL, autenticação, paginação, timeout, retry com backoff, e as funções de transformação do payload em DataFrame | Não escreve em disco nem em banco |
| **Ingestor** | `ingest_<fonte>.py` | Orquestrar a extração, gravar a **raw** comprimida antes de qualquer transformação e materializar a **bronze** (Parquet ou memória). Expõe CLI com janela (`--de`, `--ate`) e caminhos sobrescrevíveis | Não conhece o esquema do banco de destino |
| **Carregador** | `load_<fonte>.py` | Aplicar o esquema, ler a bronze e fazer `UPSERT` idempotente na **silver** | Não chama a rede |

A separação existe para que cada etapa seja testável e reexecutável isoladamente: dá para recarregar o banco a partir do Parquet sem tocar na origem, e dá para reprocessar a bronze a partir da raw sem novas requisições.

!!! note "Quando ingestor e carregador são o mesmo módulo"
    Nas séries cujo payload cabe em memória e não gera Parquet, o `ingest_*.py` também carrega, porque não há bronze em disco a separar as duas metades. É o caso das séries diárias do Banco Central. O contrato não muda — só o número de arquivos.

## Esquema e migração

| Papel | Onde vive | Responsabilidade |
|---|---|---|
| Esquema relacional | `migrations/*.sql`, numeradas | Tabelas, FKs, restrições e views do Postgres. O Compose aplica todas em ordem na **primeira** subida do volume |
| Semente de referência | migration de `seed` | Agregados, variáveis e localidades que a carga pressupõe existentes |
| Esquema analítico | `scripts/setup_duckdb*.sql`, um arquivo por fonte | Tabelas e views de features do DuckDB. Todos idempotentes (`CREATE ... IF NOT EXISTS`, `CREATE OR REPLACE VIEW`), então rodam a cada carga sem efeito colateral |
| Inicialização do analítico | `scripts/init_db.py` | Cria o arquivo DuckDB e aplica todos os `setup_duckdb*.sql` encontrados, em ordem — não precisa de edição ao entrar uma fonte nova |

A assimetria é proposital: o Postgres versiona mudança de esquema em migrations porque guarda dado transacional que não se pode recriar; o DuckDB é reconstruível a partir do Parquet, então seu esquema é declarado e reaplicado em vez de migrado.

## Infraestrutura

| Componente | Onde | Papel |
|---|---|---|
| Banco relacional | `docker-compose.yml` (serviço `db`) | PostgreSQL 16.4 com healthcheck e limite de 2 GB de memória |
| Interface do banco | `docker-compose.yml` (serviço `adminer`, perfil `tools`) | Inspeção via navegador, fora da subida padrão |
| Banco analítico | arquivo `data/duckdb/inflatrack.duckdb` | Embarcado, sem serviço: um escritor por vez, o que obriga as cargas analíticas a rodar em sequência ([ADR 0002](../adr/0002-duckdb-unico.md)) |
| Camada crua e bronze | `data/raw/` e `data/parquet/` | Uma subpasta por fonte, fora do controle de versão |

## Orquestração e verificação

| Componente | Onde | Papel |
|---|---|---|
| Comandos canônicos | `justfile` | Uma receita por etapa (`<fonte>-ingest`, `<fonte>-load`) e uma que encadeia as duas (`<fonte>`). `just --list` é a lista viva |
| Ciclo do ambiente | `justfile` | `up`, `down`, `reset` (apaga o volume e reaplica as migrations), `psql`, `db-ui` |
| Verificação de carga | `sql/verificar_carga.sql`, via `just verificar-carga` | Volume por fonte contra o esperado e meses faltando no meio da série |
| Gate de qualidade | `just check` = `fmt` + `lint` + `test` | `ruff` e `pytest` sobre clientes, transformações e idempotência do `UPSERT` |
| Testes | `tests/test_<origem>.py` | Um arquivo por cliente de origem, sobre payload de exemplo — sem rede |
| Documentação | `just docs` e `just docs-build` | MkDocs Material, compilado com `--strict` (link quebrado falha a build) |

## Configuração

Tudo por variável de ambiente, lida do `.env` (valores padrão entre parênteses). Nenhum segredo vai para o repositório, e as APIs públicas não precisam de nenhuma.

| Variável | Uso |
|---|---|
| `POSTGRES_USER` (`inflatrack`) | Usuário do banco |
| `POSTGRES_PASSWORD` (`inflatrack`) | Senha |
| `POSTGRES_HOST` (`localhost`) | Host usado pela ingestão |
| `POSTGRES_PORT` (`5432`) | Porta exposta pelo Compose |
| `POSTGRES_DB` (`inflatrack`) | Nome do banco |
| `ADMINER_PORT` (`8080`) | Porta da interface gráfica do banco |
| Chave de API da origem | Só onde a origem exige (hoje, a Alpha Vantage) |

## Mapa dos módulos

Para localizar o código de uma fonte específica:

| Fonte | Cliente | Ingestor | Carregador | Esquema |
|---|---|---|---|---|
| IPCA/INPC | `sidra.py` | `ingest.py` | (o próprio ingestor, no Postgres) | `migrations/` |
| Commodities e Energia | `alphavantage.py` | `ingest_commodities.py` | `load_commodities.py` | `setup_duckdb.sql` |
| Dólar Comercial | `dolar_olinda.py` | `ingest_dolar.py` | (o próprio ingestor) | `setup_duckdb_macro.sql` |
| Taxa SELIC | `selic_sgs.py` | `ingest_selic.py` | (o próprio ingestor) | `setup_duckdb_macro.sql` |
| PIB e Setores | `pib.py` | `ingest_pib.py` | `load_pib.py` | `setup_duckdb_pib.sql` |
| PIB da China | — | `ingest_pib_china.py` | `load_pib_china.py` | `setup_duckdb_pib_china.sql` |
| Salário Mínimo | `dieese.py` | `ingest_salario_minimo.py` | `load_salario_minimo.py` | `setup_duckdb_salario_minimo.sql` |
| Dados do Clima | `inmet.py` | `ingest_clima.py` | `load_clima.py` | `setup_duckdb_clima.sql` |
