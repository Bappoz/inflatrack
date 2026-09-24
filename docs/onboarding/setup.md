# Subir do Zero

## Requisitos

- **Docker Compose v2**
- **Python 3.12+** ou [uv](https://docs.astral.sh/uv/)
- [just](https://just.systems)

## Execução Rápida

```bash
git clone https://github.com/Bappoz/inflatrack.git && cd inflatrack
cp .env.example .env
just reset          # sobe o Postgres e aplica migrations/0001..0003 em ordem
just seed-amostra   # 3 meses do IPCA — confere que a ingestão funciona
```

Para carregar a série histórica inteira (jul/2006 a jul/2026, ~4,7 milhões de linhas):

```bash
just seed
just verificar-carga
```

!!! tip "Comandos Canônicos"
    O `justfile` é a fonte canônica dos comandos do projeto. Execute `just --list` para visualizar todas as receitas disponíveis.

