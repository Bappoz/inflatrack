# Stack tecnológica e fronteiras da plataforma

- **Status:** registro da stack em uso (atualizado após a Entrega 3) e das escolhas ainda propostas
- **Data:** 2026-10-18
- **Atualizado em:** 2026-11-09

> Esta página organiza as justificativas tecnológicas da arquitetura; não é um
> ADR numerado. O plano de trabalho reserva o ADR 0004 para comparar mecanismos
> de ingestão/CDC e registrar a escolha entre Delta Lake e Iceberg. Essas
> decisões continuam pendentes.

## Contexto

O projeto combina duas cargas diferentes: séries públicas, ingeridas em lote e
consultadas para análise, e dados próprios do lojista, que exigem transações e
integridade. Também precisa rodar localmente com ferramentas livres, preservar
respostas das fontes e permitir reprocessamento. Este registro explica a stack
visível no repositório e distingue o que já roda do que ainda é plano. Na Entrega 3 entraram dbt, a cópia da Gold para o Postgres e o Metabase; ficam como plano a camada semântica e o modelo preditivo da Entrega 4.

## Decisões em uso

| Tecnologia | Papel e justificativa | Estado e custo conhecido |
|---|---|---|
| **Python 3.12** | Linguagem comum para clientes HTTP, ingestão, tabelas Arrow/Delta e Dagster. Mantém as etapas no mesmo runtime e dá acesso às bibliotecas de dados usadas pelo projeto. | Em uso. Há `httpx` e `requests` nos clientes; os dois não representam uma decisão arquitetural distinta. Consolidar em `httpx` reduziria dependências, mas exige migração dos clientes BCB existentes. |
| **PostgreSQL 16.4** | Banco transacional para lojista, produto, reajuste e referências com chaves estrangeiras. `CHECK`, `UNIQUE`, FK e transações protegem a escrita que altera preço. A equipe já trabalha com SQL/PostgreSQL e o serviço roda localmente no Compose. | Em uso. Além do OLTP, hospeda o schema `serie` (cópia pequena da Gold, lida pelo Metabase) e é lido por CDC lógico (`wal_level=logical`). Custa manter migrations e um serviço local; a análise multifonte continua no DuckDB. |
| **DuckDB** | Banco analítico embarcado para consultas e tabelas de fontes públicas. SQL sobre o mesmo arquivo simplifica cruzamentos, sem administrar um servidor analítico separado para o volume atual. | Em uso. Arquivo único concentra o risco e permite apenas um processo escritor por vez; as cargas são serializadas. Ver [ADR 0002](../adr/0002-duckdb-unico.md). |
| **Delta Lake sobre Parquet** | Formato Bronze por fonte. Parquet é colunar e interoperável; o log Delta registra commits e versões. Com hashes e chaves implementados na ingestão, as cargas podem ser reexecutadas sem duplicação e revisões ficam rastreáveis. A resposta original de cada coleta fica na tabela `<fonte>_resposta` do próprio Delta, com o SHA-256 do corpo. | Em uso em todas as fontes, em `data/parquet/<fonte>/`. A coleta do salário mínimo ainda grava o HTML em `data/raw/dieese/` e um Parquet legado em `data/parquet/dieese/`, que o loader das tabelas da E1 lê. O projeto não deve chamar toda Bronze de Parquet simples. |
| **PyArrow** | Formato de intercâmbio entre DataFrames, tabelas Arrow, Delta Lake e leitores analíticos. Evita criar um formato privado para cada ingestão. | Em uso como dependência e ponte entre essas APIs. |
| **pandas** | Estrutura tabular usada pelos clientes e ingestores para tipagem e conversão de payloads. Facilita transformar respostas heterogêneas em lotes consistentes. | Em uso. Não é requisito para consultas no DuckDB e pode ser reduzido se uma carga futura operar diretamente em Arrow. |
| **Dagster** | Orquestra ativos de dados, dependências, retries e partições. A unidade “dado que precisa estar atualizado” corresponde ao pipeline; a interface local também permite backfill e histórico das execuções. | Em uso: coletas, cargas no DuckDB, modelos do dbt (`dagster-dbt`), cópia para o Postgres e *asset checks* de frescura de todas as fontes. O pool `duckdb_writer` limita a um escritor por vez, o que reduz o paralelismo de escrita. |
| **Docker Compose** | Sobe PostgreSQL e ferramentas locais com volumes e migrations, sem exigir serviço hospedado ou custo de infraestrutura. | Em uso. É ambiente de desenvolvimento, não uma configuração de alta disponibilidade para produção. |
| **uv + just** | `uv` sincroniza o ambiente a partir de `pyproject.toml`/`uv.lock`; `just` fornece nomes curtos e estáveis para os fluxos de execução. | Em uso. Dependem de Python e das ferramentas locais indicadas no onboarding. |
| **MkDocs Material** | Publica documentação versionada como site estático e executa build estrito para encontrar links inválidos. | Em uso, com publicação no GitHub Pages. |
| **psycopg + python-dotenv** | `psycopg` conecta os ingestores ao PostgreSQL; `python-dotenv` carrega a chave da Alpha Vantage sem gravar o segredo no código. | Em uso como dependências de integração e configuração. |
| **Ruff + pytest + Dagster Webserver** | Ruff padroniza e analisa o Python; pytest cobre ingestão, orquestração e integração com o Postgres; Dagster Webserver fornece a interface local de execução. | Ferramentas de desenvolvimento e operação local, não componentes de armazenamento. |
| **Adminer** | Interface web opcional para inspecionar o PostgreSQL durante o desenvolvimento. | Em uso via perfil `tools` do Docker Compose; não participa do runtime da aplicação. |
| **dbt-core + dbt-duckdb** | Modelos SQL versionados, dependências explícitas, testes e linhagem para transformar Bronze em Silver e Gold. Mantém as regras analíticas fora dos ingestores Python. | Em uso desde a E3: Silver em `dbt/models/staging` e `intermediate`, Gold em `marts` (com SCD tipo 2 da cesta e do preço do lojista) e 230 testes (2026-11-09). Exige `dbt parse` para atualizar o manifest que o Dagster lê. |
| **Metabase** | Painel das perguntas do lojista sem escrever código de interface. Lê só o schema `serie` do Postgres e nunca o arquivo do DuckDB, porque uma conexão aberta nele trava o dbt e os loaders. | Em uso via perfil `bi` do Docker Compose. O painel (7 perguntas) é recriado do Git com `just metabase-painel`. Isolamento por lojista (RLS) fica para a E4. |

## Decisões planejadas, ainda não adotadas

| Tecnologia proposta | Por que aparece na arquitetura | Situação |
|---|---|---|
| **Camada semântica no dbt** | Métricas das perguntas de gestão (por exemplo, perda de poder de compra desde 2006) definidas uma vez no dbt e lidas pelo painel, em vez de calculadas em cada consulta. | Planejada para a E4 (`dbt/models/semantic/`). Hoje a P2 e a P3 fazem um cálculo leve no próprio SQL. |
| **XGBoost / LightGBM** | Modelo preditivo da recomendação de reajuste, com validação *walk-forward*. | Planejado para a E4 (`src/inflatrack/predicao/`); não consta nas dependências. |
| **Jupyter + scikit-learn + MLflow** | Notebooks para exploração e MLflow para registrar parâmetros, métricas e artefatos dos experimentos. | Proposta da arquitetura inicial; o `PLAN_E3_E4.md` não os menciona. Só adotar quando houver experimento reproduzível para rastrear. |

## Alternativas e critérios

- **PostgreSQL também para análise:** rejeitado para a carga analítica atual porque
  exigiria colocar as séries de referência e o OLTP no mesmo serviço e não
  oferece a mesma simplicidade de arquivo analítico local. PostgreSQL continua
  sendo a escolha correta para reajustes e integridade transacional.
- **DuckDB também para transações:** rejeitado porque o arquivo analítico tem
  escritor serializado e não é a fronteira adequada para alterações concorrentes
  de preço e cadastro.
- **Parquet simples para toda a Bronze:** não registra commits e versões como o
  log Delta. A idempotência continua dependendo dos hashes e das chaves da
  ingestão; Parquet é o formato físico, enquanto Delta Lake organiza as tabelas
  e o log de transações.
- **Streamlit + Plotly para o painel:** previstos na arquitetura inicial, mas o plano da E3 adotou o
  Metabase, que lê só o Postgres (`serie`) e dispensa uma aplicação de interface própria.
- **Airflow no lugar de Dagster:** não escolhido porque o pipeline é descrito
  por ativos de dados, com partições e backfills. O projeto não precisa hoje de
  um serviço separado para rotinas operacionais genéricas.
- **Um serviço hospedado para desenvolvimento:** não escolhido porque a
  disciplina exige stack livre e execução em Docker Compose local.

## Consequências

- O núcleo pode ser desenvolvido e executado localmente e usa ferramentas
  compatíveis com dados em lote e SQL.
- PostgreSQL e DuckDB têm fronteiras diferentes: escrita transacional e análise
  multifonte, respectivamente. Não se deve duplicar essas responsabilidades sem
  uma necessidade medida.
- Delta Lake dá histórico e commits na Bronze, mas traz uma dependência e uma
  camada operacional além de arquivos Parquet simples.
- A arquitetura da E3 está implementada de ponta a ponta (Bronze, Silver, Gold, `serie` e
  Metabase). A camada semântica e o modelo preditivo permanecem planejados para a E4. O status
  deve ser atualizado quando forem instalados e validados no repositório.

## Gatilhos de revisão

Revisar se a carga precisar de alta disponibilidade, escrita analítica
concorrente, operação hospedada, ou se a implementação da camada semântica e do modelo
preditivo mostrar que as escolhas planejadas não atendem ao fluxo real. A adoção de cada
tecnologia planejada requer código, dependências versionadas e evidência de uso.
