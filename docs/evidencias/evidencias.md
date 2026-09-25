# Evidências

Números medidos contra a API do SIDRA e contra o Postgres real, com a data e o comando que produziu cada um. Onde há extrapolação, está dito — ver também [Fonte SIDRA/IBGE](../fontes/sidra.md).

## Volume por agregado (medido em 2026-09-08)

Uma requisição por agregado, contando linhas com valor (descartando `...`, `..`, `-`, `X`). O total por agregado é **extrapolação**: linhas do mês amostrado × número de meses publicados.

| Agregado | Período | Meses | Localidades | Categorias | Linhas/mês (medido) | Total (extrapolado) |
|---|---|---|---|---|---|---|
| 2938 | jul/2006 – dez/2011 | 66 | 12 | 465 | 12.093 | ~798 mil |
| 1419 | jan/2012 – dez/2019 | 96 | 17 | 464 | 22.784 | ~2,19 mi |
| 7060 | jan/2020 – jul/2026 | 79 | 17 | 457 | 21.620 | ~1,71 mi |
| 7063 (INPC) | jan/2020 – jul/2026 | 79 | 17 | 447 | ~21.052 | ~1,66 mi |
| 1737 (nº-índice) | dez/1979 – jul/2026 | 560 | 1 | — | — | 3.337 valores (medido, 1 única requisição) |

**~4,7 milhões de linhas** só de IPCA; ~6,4 milhões com o INPC.

## Restrições de rede da origem (medido)

| Restrição | Valor medido |
|---|---|
| Teto de valores por requisição | 50.000 — um mês do 7060 (31.076 valores) passa; dois meses (62.152) devolvem HTTP 400 |
| Tamanho por mês, formato padrão | ~10,4 MB (7060) |
| Tamanho por mês, formato compacto `/f/c/h/n` | ~4,4 MB (7060) — sem cabeçalho nem nomes |
| Tempo por requisição, formato padrão | 11–25 s por mês |
| Tempo por requisição, formato compacto | ~9 s por mês |
| Compressão gzip da camada crua | 18× (10,4 MB → 0,6 MB por mês) |
| Total baixado na carga histórica | ~2,2 GB no formato padrão; ~950 MB no compacto |

## Heterogeneidade da cesta (medido em 2026-09-08)

Comparação das listas de categorias das três tabelas de IPCA (2938, 1419, 7060), entre jul/2006 e jul/2026:

| O que mudou | Quantidade | Exemplo |
|---|---|---|
| Subitens renomeados (código estável) | 43 | `1111004` "Leite pasteurizado" → "Leite longa vida"; `3202028` "Microcomputador" → "Computador pessoal"; `9101008` "Telefone celular" → "Plano de telefonia móvel" |
| Subitens removidos | 111 | — |
| Subitens acrescentados | 103 | — |

Isso é o que justifica `classificacao_versao` como dimensão de vigência ([ADR 0001](../arquitetura.md)).

## Primeira carga real contra o Postgres (medido em 2026-09-14)

| Etapa | Resultado |
|---|---|
| `just up` — migrations do zero | 9 tabelas criadas, conferidas manualmente |
| `just seed` (agregado 2938) | Bug encontrado: `create temp table carga (like observacao including defaults)` não copia `generated always as identity`; corrigido com `including identity` |
| `just seed-amostra` (agregado 7060, mai–jul/2026) | Segundo bug encontrado e corrigido: tradução `D4C` (id interno do SIDRA) → código natural da cesta, antes ausente |
| `just seed-amostra` após as correções | **64.860 linhas inseridas**, sem erro |
| Conferência manual | `SELECT` sobre a amostra confirmou que variação mensal, acumulada em 12 meses e índice batem com o que a API devolve para o mesmo período |

Detalhe completo dos dois bugs em `AI-USAGE.md` (entrada de 2026-09-14).

## O que ainda não foi medido

- `just seed` completo (as 5 fontes, ~4,7 mi linhas) nunca rodou de ponta a ponta — só a amostra do 7060.
- O agregado 1737 (índice geral, sem dimensão de classificação) não teve o caminho de código exercitado contra a API real.
- Tamanho em disco do banco populado (a estimativa de 700 MB–1 GB em `fontes/sidra.md` não vem de medição).
- `EXPLAIN (ANALYZE, BUFFERS)` das 5 consultas do lojista — é o que falta para fechar a [Medição do ADR 0001](../arquitetura.md#medicao).
- `pytest` não cobre nada ainda; as correções de 2026-09-14 foram validadas só por execução manual.
