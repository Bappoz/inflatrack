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
