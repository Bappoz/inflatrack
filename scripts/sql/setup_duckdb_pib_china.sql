-- Indicadores anuais do PIB da China no mesmo DuckDB das demais fontes analíticas.

CREATE TABLE IF NOT EXISTS pib_china (
    ano SMALLINT PRIMARY KEY,
    crescimento_pib_pct DOUBLE,
    pib_usd DOUBLE,
    atualizado_em TIMESTAMP NOT NULL DEFAULT current_timestamp
);
