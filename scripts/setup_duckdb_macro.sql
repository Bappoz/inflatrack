-- Séries macroeconômicas diárias do Banco Central no DuckDB analítico único.

CREATE TABLE IF NOT EXISTS dolar_cotacao (
    data_referencia DATE PRIMARY KEY,
    cotacao_compra DOUBLE NOT NULL,
    cotacao_venda DOUBLE NOT NULL,
    observado BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS selic_taxa (
    data_referencia DATE PRIMARY KEY,
    taxa_dia_pct DOUBLE NOT NULL,
    observado BOOLEAN NOT NULL
);
