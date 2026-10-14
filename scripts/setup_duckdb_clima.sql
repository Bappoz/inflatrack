-- Dados climáticos e estações meteorológicas (INMET) no DuckDB analítico compartilhado.

CREATE TABLE IF NOT EXISTS estacao_meteorologica (
    estacao_id VARCHAR(10) PRIMARY KEY,
    nome VARCHAR NOT NULL,
    estado VARCHAR(2) NOT NULL,
    tipo VARCHAR(20) NOT NULL,
    latitude DOUBLE,
    longitude DOUBLE,
    altitude_m DOUBLE,
    situacao VARCHAR(20),
    atualizado_em TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS clima_diario (
    estacao_id VARCHAR(10) NOT NULL,
    data_referencia DATE NOT NULL,
    temp_min DOUBLE,
    temp_max DOUBLE,
    temp_media DOUBLE,
    precipitacao_total_mm DOUBLE,
    umidade_relativa_media_pct DOUBLE,
    umidade_relativa_min_pct DOUBLE,
    observado BOOLEAN NOT NULL DEFAULT true,
    atualizado_em TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (estacao_id, data_referencia)
);

-- Camada Bronze (espelho da tabela Delta clima_estacao)
CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.clima_estacao (
    estacao_id VARCHAR NOT NULL,
    nome VARCHAR NOT NULL,
    estado VARCHAR NOT NULL,
    tipo VARCHAR,
    latitude DOUBLE,
    longitude DOUBLE,
    altitude_m DOUBLE,
    situacao VARCHAR,
    data_inicio_operacao VARCHAR,
    data_fim_operacao VARCHAR,
    _id_resposta VARCHAR NOT NULL,
    _fonte VARCHAR NOT NULL,
    _requisicao VARCHAR NOT NULL,
    _ingerido_em TIMESTAMPTZ NOT NULL
);
