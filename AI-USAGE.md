# Registro de uso de IA

Exigido pela [Política de Uso de IA](https://unb-bd2.github.io/PlanoEnsino/) da
disciplina. Uma entrada por sessão em que assistente ou agente participou.
Ferramenta, o que fez, o que a Squad conferiu depois.

## 2026-09-08 — Claude Code (Opus 5) — levantamento das fontes e esqueleto do repositório

**O que a ferramenta fez**
- Consultou a API de metadados do IBGE (`servicodados.ibge.gov.br/api/v3/agregados`)
  e a API de valores (`apisidra.ibge.gov.br`) para caracterizar os agregados
  2938, 1419, 7060, 7063 e 1737: períodos, variáveis, categorias, localidades.
- Mediu, com requisição real: linhas com valor por mês de cada agregado, tamanho
  e tempo de resposta, teto de 50.000 valores por requisição, ganho do formato
  compacto `/f/c/h/n` e razão de compressão gzip.
- Comparou as listas de categorias das três tabelas de IPCA e levantou as
  renomeações de subitem com código estável (43), entradas (103) e saídas (111).
- Escreveu o esqueleto deste repositório: migrations, cliente da API, CLI de
  ingestão, justfile, README e o rascunho de `docs/adr/0001`.
- Preencheu parte da planilha de acompanhamento da disciplina.

**O que foi verificado e como**
- Sintaxe de todo o SQL de `migrations/` e `sql/` conferida com `pglast`
  (libpg_query, o parser do próprio PostgreSQL).
- `ruff check` e `ruff format` passam em `src/`.
- Os números de volume vieram de requisição real; os totais por agregado são
  **extrapolação** de um mês amostrado vezes o número de meses, e estão
  marcados como estimativa onde aparecem.

**O que NÃO foi verificado**
- O `docker compose up` não foi executado (daemon do Docker indisponível na
  máquina em que a sessão rodou). O esquema nunca foi aplicado num Postgres real
  e a ingestão nunca escreveu no banco. Isso é o primeiro passo da Squad.
- Nenhum benchmark de consulta foi rodado. O ADR ainda não tem medição.

**Decisões que continuam sendo da Squad**
- A escolha registrada em `docs/adr/0001` (insert-only x CRUD, normalização,
  carimbo de tempo) e as alternativas consideradas.
- O recorte de fontes: manter INPC e número-índice, ou cortar.

## 2026-09-14 — Claude Code (Sonnet 5) — primeira subida do banco e correção de bugs na ingestão

**O que a ferramenta fez**
- Subiu o Postgres pela primeira vez (`just up`), aplicando `migrations/` do
  zero num volume novo; conferiu as 9 tabelas criadas.
- Ao rodar `just seed` (agregado 2938), encontrou e corrigiu um bug em
  `ingest.py::carregar_periodo`: `create temp table carga (like observacao
  including defaults)` não copia a propriedade `generated always as identity`
  da coluna `id` — faltava `including identity`, o que quebrava todo `COPY`
  com violação de not-null.
- Ao rodar `just seed-amostra` (agregado 7060) com o primeiro bug corrigido,
  encontrou um segundo bug, mais sério: os valores do SIDRA (`/values`)
  identificam a categoria por `D4C`, que é o **id interno** da categoria
  (7169, 7170, 7171...), não pelo código natural (`1`, `11`, `1101002`...)
  que `sidra.categorias()` extrai do rótulo e que `classificacao.codigo` usa
  como chave. Os dois só coincidiam por acaso no índice geral (`7169`),
  quebrando a FK a partir da segunda categoria em diante. Corrigido
  construindo, em `sincronizar_cesta`, um mapa `id_sidra -> codigo` a partir
  dos metadados, e traduzindo `D4C` por esse mapa em `carregar_periodo`.
- Tratou o caso do agregado 1737 (série do índice geral desde 1979, sem
  dimensão de classificação — payload não tem `D4C`): mapeado para o
  sentinela `7169` (índice geral) em vez de estourar `KeyError`. Não foi
  possível confirmar em carga real porque `just seed` ainda não chegou a esse
  agregado nesta sessão.
- Corrigiu `nivel_do_codigo("7169")`, que classificava o índice geral como
  `"item"` por comprimento de string; agora reconhece o código sentinela e
  devolve `"geral"`. Como já havia uma linha gravada com o valor antigo (em
  `classificacao`, tabela de referência — não `observacao`/`reajuste`),
  corrigida com `UPDATE` pontual.
- Rodou `just seed-amostra` (agregado 7060, mai–jul/2026) com as correções:
  64.860 linhas inseridas, sem erro.
- Explicou ao usuário, ao longo da sessão, a leitura de `sql/verificar_carga.sql`
  (por que a segunda consulta fica vazia com o banco vazio) e escreveu
  consultas SQL ad-hoc para listar categorias da cesta.

**O que foi verificado e como**
- `just check` (ruff format + ruff check) passa em `src/` após as correções.
- A carga de amostra (7060, 3 meses) rodou de ponta a ponta contra o Postgres
  real, com `SELECT` manual conferindo que os valores gravados (variação
  mensal, acumulada em 12 meses, índice) batem com o que a API do SIDRA
  devolve para o mesmo período.
- `git diff` revisado manualmente antes de sugerir mensagem de commit;
  nenhum commit foi feito (pedido explícito do usuário).

**O que NÃO foi verificado**
- `just seed` completo (2938, 1419, 7060, 7063, 1737) não foi rodado nesta
  sessão — só a amostra do 7060. O agregado 1737 (índice geral sem
  classificação) não teve o caminho de código exercitado contra a API real.
- `pytest` não roda nada (`no tests ran`) — o projeto ainda não tem testes
  automatizados para `ingest.py`/`sidra.py`; a correção foi validada só por
  execução manual e inspeção do payload da API.
- `verificar-carga` não foi checado contra a série completa, só contra a
  amostra parcial de uma fonte.

**Decisões que continuam sendo da Squad**
- Adicionar teste automatizado que cubra a tradução `D4C -> codigo` e a
  criação da tabela `carga`, para não depender de execução manual contra a
  API real a cada regressão.

## 2026-09-22 — Antigravity (Gemini 3.1 Pro) — Ingestão de Commodities e Energia via Alpha Vantage

**O que a ferramenta fez**
- Escreveu o script de inicialização do banco analítico local `scripts/setup_duckdb.sql` (e o utilitário Python `scripts/init_db.py`).
- Ajustou o `PIVOT` da view DuckDB `vw_commodities_features` listando explicitamente as cotações na cláusula `IN (...)`, devido à limitação nativa do DuckDB de não suportar views com criação dinâmica de colunas a partir de dados.
- Implementou o client da API `src/inflatrack/alphavantage.py` tratando o rate limiting explícito do plano free da Alpha Vantage (pausas de ~13s).
- Desenvolveu as CLIs de ingestão `src/inflatrack/ingest_commodities.py` (download via API e armazenamento em formato apache parquet na camada *raw*) e carga `src/inflatrack/load_commodities.py` (leitura dos parquets e `UPSERT` direto no banco DuckDB).
- Adicionou as dependências de ambiente com o gerenciador `uv`: `duckdb`, `pandas`, `pyarrow`, `requests` e `python-dotenv`.
- Documentou a execução do novo pipeline de commodities em `docs/fontes/como_rodar.md`.

**O que foi verificado e como**
- A inicialização do banco rodou de forma funcional na máquina, confirmando a criação das tabelas corretas.
- O script de carga (`load_commodities.py`) foi verificado via geração de arquivos *mock* artificiais localmente usando pandas/pyarrow, provando a eficácia e tolerância a falhas na leitura dos arquivos em lote `data/commodities_raw/*.parquet` nativamente.
- O formato Wide Format para Machine Learning da View via `PIVOT` foi testado com sucesso conectando ao arquivo e usando `.df()` para inspecionar os tipos e colunas (9 features geradas + data da medição).

**O que NÃO foi verificado**
- O download real dos dados (requisições de rede à API Alpha Vantage) durante o processo, pois o `.env` estava propositalmente sem a chave de uso diário definida (`ALPHAVANTAGE_API_KEY=`).

**Decisões que continuam sendo da Squad**
- Preencher a chave `ALPHAVANTAGE_API_KEY` na configuração `.env`.
- Executar o download ponta-a-ponta para validar os schemas do JSON real retornado pela API e se os mesmos se encaixam no esperado.

## 2026-09-24 — Claude Code (Opus 5.5) — documentação da fonte IPCA/INPC no MkDocs

**O que a ferramenta fez**
- Levou para o site as linhas do IPCA/INPC da planilha de acompanhamento,
  conferindo cada afirmação contra `migrations/`, `sidra.py` e `ingest.py`:
  seção 2 e leitura do armazenamento em `fontes/sidra.md`, dicionário
  `dicionario/sidra.md` e a seção do IPCA em `pipeline/pipelineDados.md`.
- Corrigiu links quebrados (`carga.md` removido, link para `src/`) que faziam
  `mkdocs build --strict` falhar.

**O que foi verificado e como**
- `just docs-build` (`mkdocs build --strict`) passa sem warning.
- Os dois exemplos SQL do dicionário foram validados só sintaticamente com
  `pglast`; não rodaram contra o banco (Docker indisponível na sessão).

**O que NÃO foi verificado**
- Números de volume foram reaproveitados da caracterização de 2026-09-08; nada
  foi medido de novo.

## 2026-09-25 — Claude Code (Opus 5) — realinhamento dos caminhos de `data/`

**O que a ferramenta fez**
- Atualizou os scripts para a nova hierarquia de `data/` criada pela Squad:
  cru do IPCA em `data/raw/ipca-inpc/` (default do `--raw-dir` em `ingest.py`),
  cru das commodities em `data/raw/commodities_raw/`, Parquet em
  `data/parquet/` e banco em `data/duckdb/inflatrack.duckdb`
  (`load_commodities.py`, `scripts/init_db.py`, `src/dados_duck.py`).
- Tornou a ingestão de commodities de fato ELT: `ingest_commodities.py` agora
  grava a resposta da Alpha Vantage em JSON gzip na camada crua e só depois
  relê esse arquivo para gerar o Parquet — antes o Parquet nascia da resposta
  em memória e a camada crua não existia para essa fonte.

**O que foi verificado e como**
- Round-trip raw → Parquet de `ingest_commodities.py` exercitado primeiro com
  payload sintético (sem gastar cota da API), incluindo o descarte de valores
  `"."`.
- **Pipeline completo rodado do zero**, com `data/` renomeado para `data_old/`
  e a árvore reconstruída do nada: `scripts/init_db.py` criou
  `data/duckdb/inflatrack.duckdb`; `ingest_commodities --commodity ALL --modo
  historico` gerou os 9 `.json.gz` em `data/raw/commodities_raw/` e os 9
  `.parquet` em `data/parquet/`; `load_commodities` carregou 26.781 registros
  no DuckDB. As views foram inspecionadas com `src/dados_duck.py`
  (`vw_features_daily` até 2026-09-22, `vw_features_monthly` até 2026-07-01).
- **Conexão real com a Alpha Vantage:** 9 requisições HTTP bem-sucedidas
  (WTI, BRENT, NATURAL_GAS, WHEAT, CORN, COTTON, SUGAR, COFFEE,
  ALL_COMMODITIES), com o rate limiting de ~12 s entre chamadas funcionando.
  O schema do JSON real bate com o esperado por `process_response`. O total
  ficou 13 linhas acima do backup — os pregões novos das séries diárias.
- **Conexão real com o SIDRA:** `just up` subiu o Postgres e
  `ingest --agregado 7060 --de 2026-05 --ate 2026-07` fez 1 requisição à API
  de metadados (457 categorias sincronizadas) e 3 à API de valores, gravando
  `7060-202605/06/07.json.gz` em `data/raw/ipca-inpc/`. As três retornaram
  "0 linhas novas", o que confirma a idempotência: o volume `pgdata` sobreviveu
  e esses meses já estavam carregados. `observacao` segue com 5,9 mi de linhas
  nos cinco agregados.

**O que NÃO foi verificado**
- A inserção de linhas novas em `observacao`: como o volume `pgdata` não foi
  derrubado, a carga do IPCA só exercitou o caminho idempotente. Para ver o
  `COPY` inserindo de fato é preciso `just reset` antes.
- A carga histórica completa do IPCA (`just seed`, ~880 requisições ao SIDRA)
  não foi refeita — o histórico veio do backup em disco.

**Decisões que continuam sendo da Squad**
- Apagar ou manter `data_old/` (49 MB), que ficou no disco como backup.

## 2026-09-25 — Antigravity (Gemini 3.6 Flash) — Caracterização e Documentação do PIB da China

**O que a ferramenta fez**
- Mapeou os arquivos de contexto da pasta `Bancos 2/Planilha inicial` para auxiliar o integrante da squad na caracterização dos dados para a Primeira Entrega da disciplina.
- Auxiliou na escolha e justificativa técnica da inclusão do **PIB da China (World Bank API)** como variável macroeconômica explicativa da demanda por commodities.
- Preencheu tecnicamente os 5 blocos da planilha da disciplina (Fontes, Formatos, Modelos, Cargas/Engines e Pipeline) para o PIB da China.
- Criou o documento `docs/fontes/pib_china.md` no padrão MkDocs do repositório, detalhando volumetria, retenção, pureza e restrições da API do Banco Mundial.
- Atualizou o índice da arquitetura em `docs/arquitetura/fonteDados.md` e o menu de navegação em `mkdocs.yml`.

**O que foi verificado e como**
- Verificada a conformidade do formato de documentação comparando com `docs/fontes/commodities.md` e `docs/fontes/sidra.md`.
- Criada a migration `migrations/0004_pib_china.sql` e aplicada ao banco de dados PostgreSQL.
- Criado o script `src/inflatrack/ingest_pib_china.py` com padrão ELT (salva JSON em `data/raw/pib_china/` e faz UPSERT no banco).
- **Execução e validação real**: Ingestão ponta-a-ponta executada contra a API do Banco Mundial (`api.worldbank.org`), processando 66 anos de dados históricos (1960-2025) salvos na tabela `pib_china` do PostgreSQL.

**O que NÃO foi verificado**
- Testes de concorrência simultânea entre a ingestão das commodities e do PIB da China.

## 2026-09-25 — Antigravity (Gemini 3.1 Pro) — Ingestão Banco Central (Dólar Comercial e Selic)

**O que a ferramenta fez**
- Analisou o cliente de API `src/inflatrack/bcb.py` focado no SGS (Sistema Gerenciador de Séries Temporais) do Banco Central do Brasil para buscar os códigos 1 (Dólar Venda Diário) e 11 (Taxa Selic Efetiva Diária).
- Verificou o script de ingestão CLI `src/inflatrack/ingest_bcb.py` que converte a saída JSON da API para tabelas Pandas e salva localmente em blocos Parquet (`dolar.parquet` e `selic.parquet`).

**O que foi verificado e como**
- A análise dos arquivos da squad confirmou que o formato em `ingest_bcb.py` é exatamente o padrão adotado na `ingest_commodities.py` previamente feita pelo time (Silver -> Parquet, CLI com argparse, etc.).
- Conferida a existência do `docker-compose.yml` base para PostgreSQL (`inflatrack`) e checagem da estrutura de diretórios (`migrations/`, `sql/`, `scripts/`).

**O que NÃO foi verificado**
- Não foi feita a conexão direta de rede para a API do BCB por dentro do ambiente sandbox de execução.
- O script `load_bcb.py` não foi escrito ainda, o que transportaria os arquivos parquet recém baixados para o DuckDB ou PostgreSQL do projeto.

**Decisões que continuam sendo da Squad**
- Definir como juntar todos esses dados na tabela fato final (DuckDB/dbt) e estruturar o pipeline de agendamento usando o orquestrador (Dagster) prometido no fluxo.

## 2026-09-25 (Fase 2) — Antigravity (Gemini 3.1 Pro) — Finalização do Módulo de Macroeconomia

**O que a ferramenta fez**
- Revisou os arquivos de ingestão e carga, aplicando a separação de responsabilidades para o Dólar (`dolar_olinda.py`, `ingest_dolar.py`, `load_dolar.py`) e Selic (`selic_sgs.py`, `ingest_selic.py`, `load_selic.py`).
- Criou os arquivos de teste automatizado na pasta `tests/` (`test_dolar_olinda.py` e `test_selic_sgs.py`), inaugurando a cobertura de testes do projeto via `pytest` e *Mocks*.
- Revisou a documentação no MkDocs para refletir a arquitetura implementada (API Olinda, Forward Fill e DuckDB), analisando as páginas `pipelineMacro.md`, `evidencias_macro.md`, `dicionario/macroeconomia.md` e o `adr_0002_macro.md`.
---

## 2026-09-25 — Claude Code (Opus 5) — ingestão das Contas Nacionais Trimestrais (SIDRA 1846)

**Prompt da Squad**
Implementar a tabela [1846 do SIDRA](https://sidra.ibge.gov.br/tabela/1846) na
trilha existente: baixar pela API os indicadores que afetam o preço ao
consumidor (agropecuária, eletricidade e gás, serviços, comércio, transporte,
atividades financeiras, impostos sobre produtos, PIB, despesas de consumo,
exportação e importação), gravar o cru em `json.gz`, organizar em Parquet no
padrão do projeto e levar ao DuckDB — ponderando se atualizar o banco existente
ou criar um por fonte.

**O que a ferramenta fez**
- `src/inflatrack/pib.py`: catálogo da tabela 1846 — as 23 categorias da
  classificação `c11255`, a marcação de `grupo` (atividade / demanda /
  agregado) e o recorte de 12 indicadores do **núcleo** pedido pela Squad.
  Os nomes vêm dos metadados da API, não hardcoded; renomeação na origem se
  propaga sozinha.
- `src/inflatrack/ingest_pib.py`: CLI de ingestão ELT, um `json.gz` por ano em
  `data/raw/pib_raw/`, Parquet em `data/parquet/pib/`.
- `scripts/setup_duckdb_pib.sql` + `src/inflatrack/load_pib.py`: tabelas
  `pib_setor` / `pib_valor` e três views (`vw_pib_setor_trimestral`,
  `vw_pib_nucleo`, `vw_features_pib_trimestral`), com UPSERT idempotente.
- `scripts/init_db.py` passou a aplicar **todos** os `setup_duckdb*.sql`, não
  só o das commodities.
- Receitas `just pib-ingest`, `just pib-load` e `just pib`.
- Docs: `docs/fontes/pib.md` e `docs/adr/0002-duckdb-unico.md`, mais entradas
  na nav do MkDocs e nas tabelas de fontes e estrutura do README.
- Em pedidos seguintes da Squad na mesma sessão: linha da nova fonte na tabela
  de `docs/arquitetura/fonteDados.md` (ao lado de SIDRA e Alpha Vantage) e o
  grupo **Fonte Dados** da nav do MkDocs tornado retrátil — bastou remover
  `navigation.sections` das `features` do tema. Essa flag marca o grupo com a
  classe `md-nav__item--section`, que o CSS do Material renderiza como rótulo
  fixo e sem seta; sem ela o item vira `md-nav__item--nested`, com checkbox de
  toggle. `navigation.expand` foi mantida, então os grupos abrem expandidos e
  podem ser recolhidos — verificado no HTML gerado em `site/`.

**Decisão ponderada: um DuckDB ou um por fonte**
Optou-se por **manter o `inflatrack.duckdb` único**, com prefixo de tabela por
fonte. O critério foi o padrão de acesso, não o volume: a pergunta de gestão do
projeto é multifonte ("o comércio encareceu porque o frete subiu?"), e num
arquivo isso é `JOIN`, enquanto entre arquivos exige `ATTACH` em toda sessão e
impede FK entre as metades. O raciocínio completo, com as alternativas e as
quatro regras que tornam a escolha sustentável, está no ADR 0002.

**Armadilha concreta encontrada**
`inflatrack.load_commodities` lê `data/parquet/*.parquet` com glob raso e
pressupõe o esquema `(symbol, data_referencia, preco)`. Um Parquet de PIB solto
nessa pasta quebraria a carga das commodities — daí a subpasta
`data/parquet/pib/`. Também foi preciso guarda explícita em
`pib.trimestre_para_data`: o período da 1846 é `AAAATT` e não `AAAAMM`, e
reaproveitar `ingest.mes_para_data` transformaria o 3º trimestre em março sem
erro nenhum.

**O que foi verificado e como**
- **Conexão real com o SIDRA:** 1 requisição de metadados + 31 de valores (uma
  por ano, 1996–2026), todas HTTP 200, em ~9 s. Gerou 31 `json.gz` (22,5 KB) em
  `data/raw/pib_raw/` e 31 `.parquet` (202 KB) em `data/parquet/pib/`,
  totalizando 2.806 linhas — 2026 traz 46 (2 trimestres × 23), coerente com a
  periodicidade declarada nos metadados (fim em `202602`).
- **Carga no DuckDB:** 23 setores e 2.806 observações. `load_pib` rodado duas
  vezes seguidas manteve 2.806 — idempotência do UPSERT confirmada.
- **Não regrediu as commodities:** `commodity_cotacao` segue com 26.781 linhas
  e `vw_features_daily`/`vw_features_monthly` continuam listadas após a carga.
- Views inspecionadas com dado real: `vw_features_pib_trimestral` no 2T/2026
  devolve PIB de R$ 3,43 tri e as 12 colunas do núcleo; `vw_pib_nucleo` no mesmo
  trimestre mostra consumo das famílias em 61,68% do PIB e agropecuária com
  −18,81% contra o mesmo trimestre do ano anterior.
- `ruff check` e `ruff format --check` limpos nos três módulos novos;
  `mkdocs build --strict` passou.

**O que NÃO foi verificado**
- A hipótese econômica por trás do recorte do **núcleo** (que esses 12
  indicadores, e não outros, são os que mais pressionam o preço na prateleira) é
  uma sugestão da ferramenta a partir da lista da Squad — não foi testada
  estatisticamente contra a série do IPCA.
- Não há teste automatizado: o projeto ainda não tem `tests/`, e `just test`
  segue sem casos para esta fonte.
- A série da 1846 é de **valores correntes**, que misturam variação de preço e
  de quantidade. Para isolar preço seria preciso cruzar com a tabela de volume
  (deflator implícito) — fora do escopo deste pedido.

**Decisões que continuam sendo da Squad**
- O caminho da camada crua ficou em `data/raw/pib_raw/` (e não `data/pib_raw/`)
  para seguir a hierarquia criada no commit `adff981`. O flag `--raw-dir`
  permite mudar; se a Squad preferir a raiz, é trocar o default.
- Se vale trazer também a tabela de índices de volume da 1846 para separar
  preço de quantidade.
- Promover o ADR 0002 de "proposto" a "aceito".

---

## 2026-09-26 — Codex — revisão do PR de Dólar e Selic

**O que a ferramenta fez**
- Revisou o PR #3, integrou a `main` e resolveu conflitos de documentação,
  navegação e automação.
- Alinhou Dólar e Selic ao DuckDB analítico único em
  `data/duckdb/inflatrack.duckdb` e moveu o esquema para
  `scripts/setup_duckdb_macro.sql`.
- Corrigiu caminhos da camada raw, datas finais estáticas, ausência do comando
  `seed-macro`, timeouts HTTP e propagação de falhas.
- Corrigiu a semântica da série SGS 11 para taxa efetiva diária e adicionou a
  coluna `observado` para distinguir publicações do BCB de valores preenchidos.
- Ampliou os testes para transformação do calendário e UPSERT idempotente.

**O que foi verificado e como**
- Oito testes automatizados passaram.
- Uma carga real de 19–25/09/2026 consultou Olinda/PTAX e SGS, gerou sete dias
  por tabela (cinco observados e dois preenchidos) e permitiu `JOIN` diário sem
  lacunas no mesmo DuckDB.
- A documentação foi compilada com `mkdocs build --strict`.

**O que NÃO foi verificado**
- A carga histórica completa desde 2020 e a Alpha Vantage não foram reexecutadas
  para evitar consumo desnecessário de tempo e cota externa.

## 2026-09-27 — Claude Code (Opus 5) — documentação da fonte Taxa SELIC (BCB/SGS)

**O que a ferramenta fez**
- Iniciou a quebra de `docs/fontes/bcb.md` em dois documentos por indicador,
  criando `docs/fontes/selic.md` na mesma estrutura de `docs/fontes/commodities.md`.
- Escreveu as quatro seções do documento a partir da leitura do código
  (`selic_sgs.py`, `ingest_selic.py`, `scripts/setup_duckdb_macro.sql`): série
  coletada, Fonte de Origem, Conjunto de Dados/Armazenamento, Carga de trabalho
  e Restrições da origem.
- Registrou dois fatos que não estavam documentados: a Selic **não tem camada
  Parquet** (a transformação é em memória entre o raw e o DuckDB), e cada rodada
  faz `UPSERT` do calendário inteiro da janela (~2.460 linhas) para incorporar
  1 dado novo, além de arquivar de novo o `.json.gz` da janela completa.
- Adicionou a página ao `nav` do `mkdocs.yml`.

**O que foi verificado e como**
- Todos os números de schema, formato de data, retentativa, timeout e semântica
  de `observado` foram lidos diretamente dos arquivos-fonte citados.
- A ausência de camada Parquet para a Selic foi confirmada por inspeção de
  `data/parquet/` (só commodities e PIB) e do fluxo de `ingest_selic.py`.

**O que NÃO foi verificado**
- Os tamanhos do raw (~15 KB por arquivo, ~4 MB/ano) são **estimativa**:
  `data/raw/bcb/` não existe nesta máquina, a carga da Selic nunca rodou aqui.
- "Frequência de leitura: alta" descreve o uso pretendido em notebooks de treino;
  não há notebooks no repositório para confirmar.
- `mkdocs build --strict` não foi executado após a edição do `nav`.

**Decisões que continuam sendo da Squad**
- ~~Se `docs/fontes/bcb.md` deve perder a parte da Selic~~ — resolvido na Fase 2
  abaixo: a Squad pediu a remoção do `bcb.md`.
- Se vale particionar o raw do BCB por ano para eliminar a redundância apontada.

## 2026-09-27 (Fase 2) — Claude Code (Opus 5) — documentação do Dólar Comercial e remoção do `bcb.md`

**O que a ferramenta fez**
- Criou `docs/fontes/dolar.md` na mesma estrutura das demais fontes, com as
  quatro seções preenchidas a partir de `dolar_olinda.py` e `ingest_dolar.py`.
- Registrou o que é específico do Olinda/PTAX: múltiplos boletins por dia útil
  (origem da deduplicação por `dataHoraCotacao`), data em `MM-DD-YYYY` entre
  aspas simples no valor do parâmetro, payload embrulhado na chave `value`, e
  carga anterior ao fechamento do câmbio gravando valor provisório.
- Reaproveitou o aviso `!!! abstract "Decisão Arquitetural (ADR)"` do antigo
  `bcb.md` na seção "Séries coletadas" do Dólar, e escreveu um equivalente para
  a Selic (série 11 é efetiva diária, não a meta do Copom — série 432).
- Substituiu a linha única de "Dólar e Selic" por duas linhas na tabela de
  `docs/arquitetura/fonteDados.md`, ajustou o `nav` do `mkdocs.yml` e removeu
  `docs/fontes/bcb.md`.

**O que foi verificado e como**
- `uv run mkdocs build --strict` passou depois da remoção: nenhum link órfão
  para `fontes/bcb.md` restou (conferido com busca no repositório).
- Antes de remover o `bcb.md`, foi conferido que suas seções de fluxo de carga
  já estavam duplicadas em `docs/pipeline/pipelineMacro.md`.
- A afirmação de que a troca SGS→Olinda está em um ADR foi **corrigida**: o
  ADR 0003 só cobre o calendário civil e a coluna `observado`. A página diz
  agora que essa decisão ainda não tem ADR próprio.

**O que NÃO foi verificado**
- Os tamanhos do raw do Dólar são estimativa; `data/raw/bcb/` não existe nesta
  máquina e a carga não foi executada.
- A contagem de boletins por dia útil devolvida pelo `CotacaoDolarPeriodo` não
  foi medida com requisição real; está descrita qualitativamente.

**Decisões que continuam sendo da Squad**
- Se a troca SGS→Olinda merece um ADR próprio ou uma seção no ADR 0003.
- Se vale particionar o raw do BCB por ano para eliminar as janelas repetidas.

## 2026-09-27 (Fase 3) — Claude Code (Opus 5) — generalização das páginas de arquitetura

**O que a ferramenta fez**
- Reescreveu `docs/arquitetura/arquiteturaMedallion.md`, que descrevia apenas o
  IPCA/SIDRA, para cobrir as seis fontes: tabela com o significado de cada
  camada no repositório e tabela com a trilha Raw → Bronze → Silver → Gold de
  cada fonte, com os caminhos e nomes de tabela reais.
- Registrou os três padrões de bronze que o repositório tem hoje: Parquet nas
  fontes analíticas, tabela temporária `carga` no IPCA e transformação apenas em
  memória nas séries do Banco Central.
- Atualizou `docs/arquitetura/visaoGeral.md`: nova seção de fontes com as seis
  origens e seus destinos, stack com os dois bancos (Postgres e DuckDB único) e
  as bibliotecas realmente usadas, e dois requisitos não funcionais que estavam
  implícitos (idempotência da carga e resiliência a falha de origem).

**O que foi verificado e como**
- Caminhos, nomes de tabela e de view foram lidos de `src/inflatrack/*.py` e
  `scripts/setup_duckdb*.sql`; as bibliotecas, de `pyproject.toml` e dos imports.
- `uv run --group docs mkdocs build --strict` passou após cada edição.
- O status "proposto" dos ADRs 0002 e 0003 foi conferido nos próprios arquivos
  antes de citá-los.

**O que NÃO foi verificado**
- Os volumes herdados do texto anterior (~4,7 mi linhas de IPCA, ~2,2 GB de
  carga) não foram remedidos nesta sessão.
- Os requisitos de latência continuam metas de projeto, sem medição.

**Decisões que continuam sendo da Squad**
- Se Dólar e Selic merecem uma view de gold própria no DuckDB (hoje o
  cruzamento é feito no `join` de cada notebook).
- Se o `verificar-carga` deve ganhar checagens equivalentes para as fontes que
  moram no DuckDB.

---

## 2026-09-28 — Antigravity (Gemini 3.8 Flash) — Documentação, Pipeline e Dicionário de Dados do Salário Mínimo (DIEESE) e Clima Diário (INMET)

**O que a ferramenta fez**
- Caracterizou e adicionou duas novas fontes de dados ao projeto: **Salário Mínimo Nominal e Necessário (DIEESE)** e **Dados do Clima Diário (INMET)**.
- Elaborou os documentos de pipeline de dados em `docs/pipeline/pipelineSalarioMinimo.md` e `docs/pipeline/pipelineClima.md`, contendo diagramas conceituais Mermaid, fluxos ELT (Raw em gzip, Silver em Parquet e Gold no DuckDB compartilhado `inflatrack.duckdb`), garantias de idempotência e diagnóstico de falhas.
- Desenvolveu os dicionários de dados físicos em `docs/dicionario/salario_minimo.md` (tabela `salario_minimo`) e `docs/dicionario/clima.md` (dimensão `estacao_meteorologica` e fato `clima_diario`), com diagramas entidade-relacionamento (Mermaid) e consultas analíticas de exemplo (cruzamentos de chuva/geada com cotações de milho/café e poder de compra com inflação).
- Atualizou os índices e tabelas centrais do repositório: `docs/arquitetura/fonteDados.md`, `docs/dicionario/dicionario.md`, `mkdocs.yml` e `README.md`.

**O que foi verificado e como**
- `uv run mkdocs build --strict` executado e aprovado com código 0, sem alertas ou links quebrados.
- Testes reais de requisição HTTP realizados contra as origens durante a concepção:
  - Inspeção do HTML e encoding `ISO-8859-1` da tabela de 420 linhas do DIEESE.
  - Consulta ao endpoint de estações ativas do INMET (`https://apitempo.inmet.gov.br/estacoes/T`), confirmando o retorno de 673 estações com geolocalização e metadados.

**O que NÃO foi verificado**
- As CLIs de extração (`ingest_*.py`) e migrações SQL físicas para essas duas fontes não foram codificadas em disco nesta etapa, tendo sido documentadas arquiteturalmente conforme solicitado.

**Decisões que continuam sendo da Squad**
- Definir se a ingestão do clima coletará a totalidade das 673 estações nacionais ou aplicará filtro geográfico prévio para os principais polos produtores de commodities agrícolas.
- Definir a periodicidade de orquestração automatizada no Dagster/cron (mensal para o DIEESE, diária matinal para o INMET).


---

## 2026-09-28 — Claude Code (Opus 5) — atualização da seção de Arquitetura para as fontes novas

**O que a ferramenta fez**
- Reescreveu as quatro páginas de `docs/arquitetura/`: `visaoGeral.md`, `fluxoDados.md`,
  `arquiteturaMedallion.md` e `componentes.md`, que ainda descreviam seis fontes e
  ignoravam Salário Mínimo (DIEESE) e Clima (INMET).
- **Visão Geral:** passou a contar oito conjuntos de dados vindos de seis provedores,
  registrou que o DIEESE é a primeira origem sem API (raspagem de HTML) e acrescentou
  um requisito não funcional sobre acoplamento ao layout da origem.
- **Fluxo de Dados:** redesenhou o diagrama Mermaid com as seis origens e as cinco
  subpastas de raw, acrescentou a seção "Caminho das fontes analíticas" (o padrão
  cliente → ingestor → carregador), completou a tabela de cadência com PIB, PIB da
  China, DIEESE e INMET, e registrou a restrição de escritor único do DuckDB.
- **Medallion:** acrescentou as duas fontes novas à trilha de camadas, documentou o
  passo "texto para tabela" (HTML → DataFrame) na passagem raw → bronze, o reúso da
  coluna `observado` no clima e a primeira dimensão do lado analítico
  (`estacao_meteorologica`).
- **Componentes:** reescrito por **papel** em vez de por fonte, como pedido. Descreve o
  contrato dos três módulos (cliente da origem, ingestor, carregador), a assimetria
  entre migrations no Postgres e esquema declarado e reaplicado no DuckDB, a
  infraestrutura, a orquestração pelo `justfile` e a configuração por `.env`. A
  amarração com o código específico ficou numa tabela "Mapa dos módulos" ao fim.

**Avaliação pedida e recusada**
- A Squad pediu para avaliar se valia fundir `arquiteturaMedallion.md` e
  `componentes.md` num arquivo só. A recomendação foi **não fundir**: as duas páginas
  respondem perguntas diferentes (como o dado progride entre camadas × qual código
  executa cada passagem), e a fusão produziria uma página longa sem público único.
  O acoplamento entre elas foi resolvido com links cruzados.

**O que foi verificado e como**
- Todo caminho, nome de tabela, de view, de receita do `just` e de variável de ambiente
  foi lido do código antes de ser escrito: `src/inflatrack/*.py`,
  `scripts/setup_duckdb*.sql`, `scripts/init_db.py`, `justfile`, `docker-compose.yml`,
  `pyproject.toml` e `tests/`.
- Confirmado no código, e não na documentação anterior, que Dólar e Selic não têm
  `load_*.py`: o próprio `ingest_*.py` carrega. Isso virou uma nota explícita em
  Componentes.
- Confirmado que o DIEESE é parseado com `re` e `html` da biblioteca padrão, sem
  BeautifulSoup — a stack foi corrigida para dizer isso.
- `uv run --group docs mkdocs build --strict` passou, sem alerta novo.

**O que NÃO foi verificado**
- Nenhuma carga foi executada nesta sessão; nada foi conferido contra banco real.
- Os volumes herdados (~4,7 mi linhas de IPCA, ~2,2 GB) não foram remedidos.
- **Divergência encontrada e não corrigida:** `docs/pipeline/pipelineClima.md` afirma que
  a bronze do clima é Parquet particionado em `data/parquet/clima/ano=YYYY/mes=MM/`,
  mas `src/inflatrack/ingest_clima.py` grava dois arquivos planos
  (`estacoes.parquet` e `clima_diario.parquet`). As páginas de arquitetura seguem o
  código; a página de pipeline continua divergente.

**Decisões que continuam sendo da Squad**
- Resolver a divergência acima: ou o ingestor passa a particionar, ou a página de
  pipeline é corrigida.
- Se Salário Mínimo e Clima merecem views de gold próprias no DuckDB — hoje ambas
  estão marcadas como planejadas na trilha do Medallion.
- Se `just verificar-carga` deve ganhar checagens para as fontes que moram no DuckDB
  (pergunta que já vinha aberta da sessão anterior e segue aberta).

---

## 2026-09-28 — Claude Code (Opus 5) — discussão: migrar o IPCA para o DuckDB

Sessão de **análise, sem alteração de código ou de esquema**. A Squad perguntou se
mover o IPCA para o DuckDB quebraria o fluxo atual.

**O que a ferramenta fez**
- Reconstruiu o quadro a partir do código, e não da documentação: `migrations/0001`,
  `migrations/0002`, `migrations/0003`, `src/inflatrack/ingest.py`,
  `scripts/setup_duckdb*.sql`, `justfile` e os dois ADRs existentes. Registrou que a
  "discussão anterior" citada pela Squad **não está no repositório** (nem em ADR, nem em
  commit, nem neste arquivo).
- Mediu, com DuckDB e 6,4 mi de linhas sintéticas no formato de `observacao`:
  pergunta 1 (subitem+praça+variável, 24 meses) em **14 ms**, pergunta 3 (série inteira
  agregada) em **20 ms**, tabela em Parquet comprimido em **39,4 MB**, e confirmou que
  `ON CONFLICT DO NOTHING` funciona com o `UNIQUE` de 6 colunas que a carga usa hoje.
  Conclusão: desempenho não é o obstáculo e a semântica insert-only sobrevive.
- Confirmou que o DuckDB suporta FK dentro do arquivo (já em uso em
  `pib_valor → pib_setor`) e que a extensão `postgres` instala e carrega, então `ATTACH`
  de Postgres é possível.
- Identificou o obstáculo real: as **três FKs do transacional** apontando para a
  referência do IPCA (`lojista.codigo_localidade`, `lojista.codigo_grupo_ipca`,
  `produto.codigo_subitem_ipca`). FK entre engines não existe, e o comentário da própria
  migration diz que sem essa garantia "o painel calcula reajuste sobre a categoria
  errada e nada acusa o erro".
- Levantou os efeitos colaterais: pergunta 5 e pergunta 1 virariam cross-engine,
  `just verificar-carga` precisaria de reescrita, e a carga mais longa do projeto
  (`just seed`) passaria a bloquear as outras pela regra de escritor único do ADR 0002.
- Depois de a Squad apontar que o IPCA é o **alvo** do modelo preditivo, revisou o peso
  do argumento: todas as outras sete fontes estão documentadas como variáveis
  explicativas, todas as views de feature estão no DuckDB e o alvo está no Postgres —
  hoje não existe consulta única que monte a matriz de treino. Isso reforça mover o
  **fato**, não as dimensões, já que o treino consome as colunas de `observacao` e não
  os nomes de `classificacao_versao`.
- Levantou duas armadilhas de gold que a migração expõe: (a) sendo insert-only, uma
  revisão do IBGE deixa mais de uma linha por chave, e um `SELECT` de treino ingênuo
  duplica o mês revisado sem erro — precisa desempatar por `ingerido_em`; (b)
  granularidades diferentes (diária, mensal, trimestral, anual) exigem espinha mensal e
  defasagem, porque o IPCA do mês M só é publicado entre os dias 9 e 12 de M+1 e usar
  feature do próprio mês M vaza futuro. A variável 2265 (acumulado 12 meses) é função do
  alvo e não pode entrar como feature.

**Recomendação registrada**
- Mover só `observacao` para o DuckDB; dimensões ficam no Postgres e são replicadas
  read-only para o DuckDB, preservando FK real nos dois lados. Entregável que fecha a
  história: uma view `vw_treino_ipca_mensal`.

**O que foi verificado e como**
- Os números acima vieram de execução real de DuckDB nesta sessão, com dado
  **sintético** no formato do `observacao`.
- As FKs, restrições e comentários citados foram lidos das migrations, não da
  documentação.

**O que NÃO foi verificado**
- **O benchmark não usou dado real do IPCA.** A cardinalidade sintética aproxima a real
  (460 subitens, 17 localidades, 5 fontes, 560 meses, 4 variáveis), mas não a reproduz;
  os tempos devem ser refeitos sobre a série carregada antes de entrarem num ADR como
  medição.
- Nada foi medido no Postgres para comparação — a Medição do ADR 0001 continua pendente.
- Nenhuma linha de código, esquema ou migration foi alterada.

**Decisões que continuam sendo da Squad**
- Escolher entre mover só o fato, mover o IPCA inteiro, ou não mover antes de resolver a
  Medição do ADR 0001.
- Escrever o ADR 0004, que revisita o ADR 0002 (escopado explicitamente a "só a camada
  analítica") e decide o destino da Medição pendente do ADR 0001, que compara CRUD ×
  insert-only dentro do Postgres e perde o sentido como está escrita se o engine mudar.
