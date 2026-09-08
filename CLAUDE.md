# InflaTrack — inflação setorial do IPCA para decisão de reajuste do pequeno lojista

## Stack
Python 3.12+ (uv) · PostgreSQL 16 em Docker Compose · ruff · pytest · just

## Comandos
```bash
just reset          # do zero: derruba volume, sobe o banco, aplica migrations em ordem
just seed-amostra   # 3 meses do IPCA — carga rápida de verificação
just seed           # série completa jul/2006 -> jul/2026 (~4,7 mi de linhas)
just verificar-carga
just check          # fmt + lint + test — o gate antes de dizer "pronto"
```
`justfile` é a fonte canônica. Não rodar o comando cru.

## Arquitetura
- `migrations/` — esquema físico; roda via `/docker-entrypoint-initdb.d` na PRIMEIRA subida. Alterar esquema = migration nova, nunca editar aplicada.
- `src/inflatrack/sidra.py` — cliente da API; concentra tudo que é quirk da origem.
- `src/inflatrack/ingest.py` — ELT: crua em `data/raw/*.json.gz`, depois `COPY` para tabela temp e merge.
- `sql/` — consultas de verificação. `docs/adr/` — decisões. `docs/carga.md` — caracterização da carga.
- Decisão central (origem insert-only, cesta com vigência): `docs/adr/0001-modelagem-do-sistema-de-origem.md`.

## Convenções (não-negociáveis)
- `observacao` e `reajuste` são **insert-only**. Nunca `UPDATE` nelas: revisão do IBGE e reajuste de preço entram como linha nova. Preço corrente sai da view `produto_preco_atual`.
- Dinheiro em centavos (`integer`). Percentual em `numeric`. Tempo em `timestamptz`.
- Nome de categoria mora em `classificacao_versao`, nunca colado no código da cesta.
- Commits: Conventional Commits, subject imperativo ≤72 chars.

## Armadilhas
- **`-` é ambíguo na API**: sozinho é ausente, `-0.67` é deflação. Use `sidra.eh_ausente`, nunca `startswith("-")`.
- **Teto de 50.000 valores por requisição no SIDRA**: um mês do 7060 são 31.076 e passa, dois estouram. Paginação mensal é imposição da origem.
- **O agregado 2938 não tem a variável 2265** (acumulada em 12 meses) e cobre só 12 localidades. Consulta que atravessa 2011/2012 sem tratar isso devolve série truncada em silêncio.
- **`just up` não reaplica migration** em volume já existente. Para esquema novo, `just reset`.
- Docker exige daemon ativo (`sudo systemctl start docker`) — propor ao usuário, não executar.

## Evitar
- Réplica colunar, dbt, orquestrador e camada semântica: são E2/E3/E4, não agora.
- `data/` versionado. A camada crua é reprodutível a partir da API; o repo guarda o script, não o dado.
- Dado de lojista em recorte analítico: CNPJ de MEI se confunde com pessoa física.

## Estado
Fonte da verdade = git (`git log --oneline -5`, branch atual).
