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
