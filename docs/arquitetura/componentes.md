# Componentes

As peças da plataforma, na ordem em que o dado as atravessa. Cada componente traz o seu papel, a ficha técnica e as responsabilidades que assume.

A linha `Status` distingue o que já roda no repositório do que está decidido e ainda não implementado. As camadas que esses componentes materializam estão em [Arquitetura Medallion](arquiteturaMedallion.md); o percurso do dado, em [Fluxo de Dados](fluxoDados.md).

## Clientes de origem (Python)

**Papel**: Extração — falar com cada origem e devolver o payload sem interpretá-lo.

| Aspecto | Detalhe |
|---|---|
| Módulos | `src/inflatrack/<origem>.py` (`sidra`, `alphavantage`, `dolar_olinda`, `selic_sgs`, `pib`, `dieese`, `inmet`, Banco Mundial) |
| Bibliotecas | `httpx`, `requests` |
| Origens | 6 provedores, 10 conjuntos de dados |
| Autenticação | Só Alpha Vantage (chave gratuita com cota diária) |
| Resiliência | Timeout explícito e retry com backoff |
| Status | Em uso |

**Responsabilidades**:

* Montar URL, autenticação e paginação de uma origem só
* Traduzir o payload em `DataFrame`, sem gravar em disco nem em banco
* Falhar com exceção própria (`SidraError`, `InmetError`, …) em payload inesperado
* Isolar o resto do sistema do formato da origem

## Ingestores (Python)

**Papel**: Aterrissagem — gravar a camada Raw e materializar a Bronze.

| Aspecto | Detalhe |
|---|---|
| Módulos | `src/inflatrack/ingest_<fonte>.py` |
| Bibliotecas | `pandas`, `pyarrow`, `deltalake` |
| Entrada | Payload do cliente de origem |
| Saída | `data/raw/<fonte>/` e tabelas em `data/parquet/<fonte>/`; alguns fluxos legados gravam Parquet diretamente |
| Interface | CLI com janela (`--de`, `--ate`) e caminhos sobrescrevíveis |
| Status | Em uso |

**Responsabilidades**:

* Gravar a resposta crua comprimida **antes** de qualquer transformação
* Converter o payload em Parquet, acrescentando a data de ingestão e a procedência
* Expor janela de tempo, para permitir backfill
* Encerrar com código diferente de zero quando a origem falhar

## Camada Raw (arquivos comprimidos)

**Papel**: Aterrissagem imutável — a origem exatamente como veio.

| Aspecto | Detalhe |
|---|---|
| Formato | `.json.gz` nas APIs, `.html.gz` no DIEESE |
| Caminho | `data/raw/<fonte>/` |
| Compressão | gzip (~18× no SIDRA) |
| Escrita | Uma vez, nunca reescrita |
| Versionamento | Fora do Git |
| Status | Em uso |

**Responsabilidades**:

* Guardar a prova do que a origem devolveu, para auditoria
* Permitir reprocessar a Bronze sem nova chamada de rede
* Preservar o HTML do DIEESE, cuja extração depende do layout e quebra sozinha
* Sustentar a retenção permanente que as fontes exigem

## Camada Bronze (Delta Lake sobre Parquet)

**Papel**: Primeira materialização estruturada, ainda por fonte.

| Aspecto | Detalhe |
|---|---|
| Formato | Tabelas Delta Lake, cujos dados são arquivos Parquet |
| Caminho | `data/parquet/<fonte>/` |
| Transformação | Só parsing e tipagem — nenhuma regra de negócio |
| Interface | Lida pelas APIs Delta/Arrow nos ingestores; dbt como *source* é planejado |
| Volumetria | A carga E2 medida contém 9,1 mi de linhas Delta do SIDRA; os arquivos Parquet compactados ocupam dezenas de MB |
| Status | Em uso em fontes migradas para E2; ainda há fluxos legados em Parquet direto |

**Responsabilidades**:

* Oferecer uma tabela estruturada por fonte, independente do formato da origem
* Recarregar o banco analítico sem tráfego de rede
* Isolar uma subpasta por fonte, para que esquemas diferentes não se misturem
* Levar a procedência de cada linha até a Silver

## dbt (Data Build Tool)

**Papel**: Transformação de dados — modelar e tratar a camada Silver.

| Aspecto | Detalhe |
|---|---|
| Versão | dbt-core |
| Adapter | `dbt-duckdb` |
| Models | `models/staging/` (Silver), `models/marts/` (Gold) |
| Sources | Tabelas Delta/Parquet da Bronze |
| Tests | Esquema, unicidade, integridade referencial, volume e distribuição |
| Docs | `dbt docs generate` (grafo de linhagem) |
| Status | Planejado; `dbt-core`, `dbt-duckdb` e `models/` ainda não existem no projeto |

**Responsabilidades**:

* Limpar, tipar e deduplicar cada fonte (Silver)
* Construir fato, dimensão e métricas (Gold)
* Testar qualidade dentro da transformação, não como etapa separada
* Documentar a linhagem entre camadas, em código versionado

## DuckDB

**Papel**: Banco analítico embarcado para as cargas e consultas analíticas atuais; Silver e Gold conformadas são o alvo futuro.

| Aspecto | Detalhe |
|---|---|
| Deploy | Embarcado, arquivo único |
| Caminho | `data/duckdb/inflatrack.duckdb` |
| Estruturas | Tabelas e views por fonte criadas por `scripts/setup_duckdb*.sql` e módulos `load_*` |
| Conexão | Ingestores e Dagster; dbt, notebooks e Streamlit são planejados |
| Concorrência | **Um escritor por arquivo, por vez** |
| Status | Em uso |

**Responsabilidades**:

* Armazenar tabelas e views analíticas de fontes no mesmo arquivo
* Permitir cruzamentos entre fontes com SQL
* Servir como destino planejado para modelos dbt e matriz de treino

## PostgreSQL

**Papel**: Banco transacional — o lado com escrita de verdade.

| Aspecto | Detalhe |
|---|---|
| Versão | PostgreSQL 16.4 |
| Deploy | Docker Compose (`docker-compose.yml`), limite de 2 GB |
| Schemas | Referência do IPCA e transacional do lojista |
| Migrations | `migrations/*.sql`, aplicadas em ordem na primeira subida |
| UI | Adminer em `http://localhost:8080` (perfil `tools`) |
| Status | Em uso |

**Responsabilidades**:

* Garantir A, C e I ao aplicar um reajuste
* Sustentar as FKs de `produto` e `lojista` para a cesta e a localidade do IPCA
* Guardar referências e a tabela insert-only de observações do IBGE
* Aplicar restrições e transações no cadastro e no histórico de reajustes
* A dimensão `classificacao_versao` preserva renomeações desde a migration `0004`; ver [ADR 0001](../arquitetura.md)

### Quando usar DuckDB vs PostgreSQL

| Situação | Banco |
|---|---|
| Aplicar reajuste, cadastrar produto ou lojista | PostgreSQL — precisa de transação |
| Consulta analítica cruzando fontes | DuckDB — colunar, tudo num arquivo |
| Treino de modelo preditivo | DuckDB — o alvo e as features moram juntos |
| Plano de execução com `BUFFERS` | PostgreSQL — o DuckDB não implementa essa opção |
| Escrita concorrente de vários usuários | PostgreSQL — o DuckDB aceita um escritor por vez |

## Dagster

**Papel**: Orquestração orientada a ativo de dado.

| Aspecto | Detalhe |
|---|---|
| Deploy | Local (`just orquestrador`, que roda `dagster dev`) |
| Código | `orchestration/` — um asset por etapa, chamando `src/inflatrack/` |
| Integração | `dagster-dbt` planejado; dbt ainda não está instalado |
| Partições | Mensais no IPCA/INPC, acompanhando a divulgação do IBGE |
| Confiabilidade | Retry por asset e backfill por partição |
| Concorrência | Pool `duckdb_writer` com limite 1 |
| Status | Em uso nos ingestores · Planejado na integração com dbt |

**Responsabilidades**:

* Executar os assets de ingestão implementados num grafo de dependência
* Repetir o que falhou sem reprocessar o que já passou
* Rodar backfill de janela histórica, por partição
* Expor o estado de execução dos assets; freshness checks ainda estão planejados

## Jupyter Notebooks

**Papel**: Experimentação — testar e visualizar as modelagens.

| Aspecto | Detalhe |
|---|---|
| Linguagem | Python 3.12 |
| Entrada | Tabelas da Gold no DuckDB |
| Bibliotecas | `pandas`, `duckdb`, `scikit-learn` |
| Conexão | DuckDB em modo leitura |
| Status | Planejado |

**Responsabilidades**:

* Explorar a matriz de treino e a relação entre features e IPCA
* Treinar e comparar modelos candidatos
* Registrar cada execução no MLflow
* Documentar a escolha do modelo com evidência

## MLflow

**Papel**: Rastreamento de experimentos de aprendizado de máquina.

| Aspecto | Detalhe |
|---|---|
| Deploy | Local (`mlflow ui`) |
| Backend | Arquivo local |
| Registra | Parâmetros, métricas, artefatos e versão do modelo |
| Integração | Chamado dos notebooks |
| Status | Planejado |

**Responsabilidades**:

* Guardar parâmetros e métricas de cada treino
* Permitir comparar execuções sem planilha à parte
* Versionar o modelo escolhido
* Ligar o resultado à janela de dado que o gerou

## Streamlit + Plotly

**Papel**: Painel analítico — a resposta ao lojista.

| Aspecto | Detalhe |
|---|---|
| Framework | Streamlit |
| Gráficos | Plotly |
| Entrada | Cópia publicada da Gold, em leitura |
| Escopo | As 5 perguntas de gestão declaradas na E1 |
| Status | Planejado |

**Responsabilidades**:

* Responder às perguntas declaradas, e não exibir os gráficos disponíveis
* Ler uma cópia publicada, para não disputar o escritor do DuckDB
* Mostrar o reajuste sugerido e o dado que o sustenta
* Declarar em tela a data do último dado carregado

## MkDocs Material

**Papel**: Documentação do projeto.

| Aspecto | Detalhe |
|---|---|
| Tema | Material for MkDocs |
| Configuração | `mkdocs.yml` |
| Build | `just docs-build` (`mkdocs build --strict`) |
| Servidor local | `just docs` |
| Publicação | GitHub Pages (`.github/workflows/docs.yml`) |
| Status | Em uso |

**Responsabilidades**:

* Publicar arquitetura, fontes, pipelines e dicionário de dados
* Falhar a build em link quebrado (`--strict`)
* Guardar os ADRs junto do código que eles decidem
* Registrar o uso de IA em `AI-USAGE.md`

## just + uv

**Papel**: Automação e ambiente reprodutível.

| Aspecto | Detalhe |
|---|---|
| Receitas | `justfile` (`just --list` é a lista viva) |
| Ambiente | `uv`, a partir de `pyproject.toml` |
| Python | 3.12 |
| Qualidade | `just check` = `ruff format` + `ruff check` + `pytest` |
| Status | Em uso |

**Responsabilidades**:

* Dar um comando canônico para cada etapa do pipeline
* Fixar as versões das dependências entre as máquinas da Squad
* Rodar o gate de qualidade antes de dizer "pronto"
* Subir e derrubar o ambiente (`up`, `down`, `reset`)

## Configuração

**Papel**: Parametrização por ambiente, sem segredo no repositório.

| Aspecto | Detalhe |
|---|---|
| Arquivo | `.env`, carregado pelo `just` e pelo `python-dotenv` |
| Banco | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` |
| Interface | `ADMINER_PORT` (`8080`) |
| Chaves de API | Só onde a origem exige (hoje, a Alpha Vantage) |
| Status | Em uso |

**Responsabilidades**:

* Manter credencial fora do controle de versão
* Permitir que cada integrante rode com porta e host próprios
* Dar valor padrão a tudo que não é segredo
* Ser a única fonte de configuração dos ingestores e do Compose
