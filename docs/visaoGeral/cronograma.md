# Cronograma

Espaço reservado para o acompanhamento semanal e retrospectivas do Squad (Banco de Dados 2 — Engenharia de Software, FCTE/UnB).

---

## Objetivo

Registrar decisões tomadas, marcos atingidos, impedimentos identificados e próximos passos a cada sprint/semana de trabalho.

---

## Registro Semanal

### Semana 1 (08/09/2026)

- Estruturação inicial do repositório com Docker Compose, PostgreSQL 16, `uv` e `just`.
- Modelagem inicial do esquema físico com migrations versionadas.
- Implementação do cliente ELT para o SIDRA/IBGE com suporte ao formato compacto `/f/c/h/n`.
- Caracterização das 5 fontes do IPCA/INPC (volume, restrições de rede, heterogeneidade da cesta) — ver [Evidências](../evidencias/evidencias.md).
- Abertura do [ADR 0001](../arquitetura.md) (proposto, sem medição ainda).

### Semana 2 (14/09/2026)

- Primeira subida real do Postgres (`just up`) com as migrations aplicadas do zero.
- Dois bugs encontrados e corrigidos na carga do IPCA: `create temp table ... including identity` ausente, e tradução do id interno do SIDRA (`D4C`) para o código natural da cesta — detalhe em [Evidências](../evidencias/evidencias.md#primeira-carga-real-contra-o-postgres-medido-em-2026-09-14).
- Primeira carga de amostra bem-sucedida contra o banco real: 64.860 linhas (agregado 7060, mai–jul/2026), conferida manualmente contra a API.

### Semana 3 (22–24/09/2026)

- Configuração do MkDocs com GitHub Pages para documentação contínua.
- Ingestão de commodities e energia via Alpha Vantage: cliente da API, carga em Parquet e base analítica em DuckDB (`vw_commodities_features`).
- Documentação da fonte IPCA/INPC no site: dicionário de dados (SIDRA e transacional), pipeline, arquitetura (visão geral, fluxo de dados, medallion, componentes) e evidências.
