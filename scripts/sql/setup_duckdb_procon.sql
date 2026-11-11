-- Cesta Básica do PROCON no DuckDB analítico compartilhado.

CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.procon_cesta_basica (
    data_pesquisa DATE NOT NULL,
    produto VARCHAR NOT NULL,
    unidade VARCHAR NOT NULL,
    preco_medio DOUBLE NOT NULL,
    preco_minimo DOUBLE,
    preco_maximo DOUBLE,
    praca VARCHAR NOT NULL,
    codigo_subitem_ipca VARCHAR,
    _id_resposta VARCHAR NOT NULL,
    _fonte VARCHAR NOT NULL,
    _requisicao VARCHAR NOT NULL,
    _ingerido_em TIMESTAMPTZ NOT NULL
);
