# 0004 — Stack tecnológica e fronteiras da plataforma

- **Status:** adotado parcialmente; decisões planejadas identificadas abaixo
- **Data:** 2026-10-18
- **Decisores:** Squad InflaTrack

## Contexto

O projeto combina duas cargas diferentes: séries públicas, ingeridas em lote e
consultadas para análise, e dados próprios do lojista, que exigem transações e
integridade. Também precisa rodar localmente com ferramentas livres, preservar
respostas das fontes e permitir reprocessamento. Este ADR registra o motivo da
stack visível no repositório e distingue o que já roda do que ainda é plano.

## Decisões em uso

| Tecnologia | Papel e justificativa | Estado e custo conhecido |
|---|---|---|
| **Python 3.12** | Linguagem comum para clientes HTTP, ingestão, tabelas Arrow/Delta e Dagster. Mantém as etapas no mesmo runtime e dá acesso às bibliotecas de dados usadas pelo projeto. | Em uso. Há `httpx` e `requests` nos clientes; os dois não representam uma decisão arquitetural distinta. Consolidar em `httpx` reduziria dependências, mas exige migração dos clientes BCB existentes. |
| **PostgreSQL 16.4** | Banco transacional para lojista, produto, reajuste e referências com chaves estrangeiras. `CHECK`, `UNIQUE`, FK e transações protegem a escrita que altera preço. A equipe já trabalha com SQL/PostgreSQL e o serviço roda localmente no Compose. | Em uso. Custa manter migrations e um serviço local; fica limitado ao papel OLTP, sem ser o destino da análise multifonte. |
| **DuckDB** | Banco analítico embarcado para consultas e tabelas de fontes públicas. SQL sobre o mesmo arquivo simplifica cruzamentos, sem administrar um servidor analítico separado para o volume atual. | Em uso. Arquivo único concentra o risco e permite apenas um processo escritor por vez; as cargas são serializadas. Ver [ADR 0002](0002-duckdb-unico.md). |
| **Delta Lake sobre Parquet** | Formato Bronze por fonte. Parquet é colunar e interoperável; o log Delta acrescenta versões transacionais para reexecução, detecção de duplicatas e auditoria de revisões. As respostas originais ficam separadas em JSON/HTML gzip na Raw. | Em uso nas tabelas Bronze da E2, em `data/parquet/`; alguns comandos legados ainda carregam Parquet diretamente. O projeto não deve chamar toda Bronze de Parquet simples. |
| **PyArrow** | Formato de intercâmbio entre DataFrames, tabelas Arrow, Delta Lake e leitores analíticos. Evita criar um formato privado para cada ingestão. | Em uso como dependência e ponte entre essas APIs. |
| **pandas** | Estrutura tabular usada pelos clientes e ingestores para tipagem e conversão de payloads. Facilita transformar respostas heterogêneas em lotes consistentes. | Em uso. Não é requisito para consultas no DuckDB e pode ser reduzido se uma carga futura operar diretamente em Arrow. |
| **Dagster** | Orquestra ativos de dados, dependências, retries e partições. A unidade “dado que precisa estar atualizado” corresponde ao pipeline; a interface local também permite backfill e histórico das execuções. | Em uso para ingestões. A integração `dagster-dbt` ainda não está instalada, pois o projeto dbt não existe. Serializar DuckDB reduz paralelismo de escrita. |
| **Docker Compose** | Sobe PostgreSQL e ferramentas locais com volumes e migrations, sem exigir serviço hospedado ou custo de infraestrutura. | Em uso. É ambiente de desenvolvimento, não uma configuração de alta disponibilidade para produção. |
| **uv + just** | `uv` sincroniza o ambiente a partir de `pyproject.toml`/`uv.lock`; `just` fornece nomes curtos e estáveis para os fluxos de execução. | Em uso. Dependem de Python e das ferramentas locais indicadas no onboarding. |
| **MkDocs Material** | Publica documentação versionada como site estático e executa build estrito para encontrar links inválidos. | Em uso, com publicação no GitHub Pages. |
| **psycopg + python-dotenv** | `psycopg` conecta os ingestores ao PostgreSQL; `python-dotenv` carrega a chave da Alpha Vantage sem gravar o segredo no código. | Em uso como dependências de integração e configuração. |
| **Ruff + pytest + Dagster Webserver** | Ruff padroniza e analisa o Python; pytest cobre os módulos de ingestão; Dagster Webserver fornece a interface local de execução. | Ferramentas de desenvolvimento e operação local, não componentes de armazenamento. |
| **Adminer** | Interface web opcional para inspecionar o PostgreSQL durante o desenvolvimento. | Em uso via perfil `tools` do Docker Compose; não participa do runtime da aplicação. |

## Decisões planejadas, ainda não adotadas

| Tecnologia proposta | Por que aparece na arquitetura | Situação |
|---|---|---|
| **dbt-core + dbt-duckdb** | Modelos SQL versionados, dependências explícitas, testes e linhagem para transformar Bronze em Silver/Gold. Mantém regras analíticas fora dos ingestores Python. | Planejado; não consta em `pyproject.toml` e ainda não há `models/`. Validar com os modelos reais antes de tratar como componente em uso. |
| **Streamlit + Plotly** | Caminho curto para apresentar filtros, indicadores e gráficos interativos sobre a camada Gold em uma interface Python. | Planejado; não consta nas dependências nem há painel no repositório. |
| **Jupyter + scikit-learn + MLflow** | Notebooks para exploração e comparação de modelos; MLflow para registrar parâmetros, métricas e artefatos de cada experimento. | Planejado; não consta nas dependências. Só adotar quando houver matriz Gold e experimento reproduzível para rastrear. |

## Alternativas e critérios

- **PostgreSQL também para análise:** rejeitado para a carga analítica atual porque
  exigiria colocar as séries de referência e o OLTP no mesmo serviço e não
  oferece a mesma simplicidade de arquivo analítico local. PostgreSQL continua
  sendo a escolha correta para reajustes e integridade transacional.
- **DuckDB também para transações:** rejeitado porque o arquivo analítico tem
  escritor serializado e não é a fronteira adequada para alterações concorrentes
  de preço e cadastro.
- **Parquet simples para toda a Bronze:** insuficiente para o histórico de
  versões e a idempotência transacional que a E2 precisa. Parquet continua sendo
  o formato físico; Delta Lake é a tabela e o log de transações.
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
- O pipeline ainda não é a arquitetura completa descrita como alvo: dbt, painel
  e ML permanecem planejados. O status deve ser atualizado quando forem
  instalados e validados no repositório.

## Gatilhos de revisão

Revisar se a carga precisar de alta disponibilidade, escrita analítica
concorrente, operação hospedada, ou se a implementação das camadas dbt/painel/ML
mostrar que as escolhas planejadas não atendem ao fluxo real. A adoção de cada
tecnologia planejada requer código, dependências versionadas e evidência de uso.
