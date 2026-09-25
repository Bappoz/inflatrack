set dotenv-load := true

_default:
    @just --list

# Sobe o banco. As migrations de migrations/ rodam em ordem na PRIMEIRA subida.
up:
    docker compose up -d --wait

down:
    docker compose down

# Do zero, em máquina limpa: apaga o volume e reaplica migrations/0001..0003.
reset:
    docker compose down -v
    docker compose up -d --wait

psql:
    docker compose exec db psql -U "${POSTGRES_USER:-inflatrack}" -d "${POSTGRES_DB:-inflatrack}"

# Amostra rápida: 3 meses do IPCA atual. Use para conferir que a carga funciona.
seed-amostra:
    uv run python -m inflatrack.ingest --agregado 7060 --de 2026-05 --ate 2026-07

# Carga histórica completa jul/2006 -> jul/2026 (~2,2 GB, dezenas de minutos; ver docs/carga.md).
seed:
    uv run python -m inflatrack.ingest --agregado 2938 --de 2006-07 --ate 2011-12
    uv run python -m inflatrack.ingest --agregado 1419 --de 2012-01 --ate 2019-12
    uv run python -m inflatrack.ingest --agregado 7060 --de 2020-01 --ate 2026-07
    uv run python -m inflatrack.ingest --agregado 7063 --de 2020-01 --ate 2026-07
    uv run python -m inflatrack.ingest --agregado 1737 --de 1979-12 --ate 2026-07

# Confere se a carga bate com o volume esperado por fonte.
verificar-carga:
    docker compose exec -T db psql -U "${POSTGRES_USER:-inflatrack}" -d "${POSTGRES_DB:-inflatrack}" \
        -f /dev/stdin < sql/verificar_carga.sql

fmt:
    uv run ruff format src/

lint:
    uv run ruff check src/

test:
    uv run pytest

# O gate antes de dizer "pronto".
check: fmt lint test

# Sobe servidor local de documentação (MkDocs) com live-reload.
docs:
    uv run --group docs mkdocs serve

# Compila a documentação estática validando integridade e links.
docs-build:
    uv run --group docs mkdocs build --strict

# Carga isolada do Dólar (Extração, Transformação e Carga Analítica)
seed-dolar:
    uv run python src/inflatrack/ingest_dolar.py --de 2020-01-01 --ate 2026-07-31

# Carga isolada da Selic (Extração, Transformação e Carga Analítica)
seed-selic:
    uv run python src/inflatrack/ingest_selic.py --de 2020-01-01 --ate 2026-07-31

# Carga isolada das Commodities (AlphaVantage -> DuckDB)
seed-commodities:
    uv run python src/inflatrack/ingest_commodities.py --commodity ALL --modo historico
    uv run python src/inflatrack/load_commodities.py
