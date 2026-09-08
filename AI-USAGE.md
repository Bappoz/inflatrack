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
