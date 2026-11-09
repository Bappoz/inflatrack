-- Salário mínimo nominal e necessário (DIEESE) no DuckDB analítico compartilhado.

CREATE TABLE IF NOT EXISTS salario_minimo (
    ano_mes VARCHAR(7) PRIMARY KEY,
    data_referencia DATE NOT NULL,
    ano SMALLINT NOT NULL,
    mes TINYINT NOT NULL,
    salario_nominal DOUBLE NOT NULL,
    salario_necessario DOUBLE NOT NULL,
    multiplo_necessario_nominal DOUBLE NOT NULL,
    atualizado_em TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- Camada Bronze (espelho da tabela Delta salario_minimo_mes)
CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.salario_minimo_mes (
    ano_mes VARCHAR NOT NULL,
    data_referencia DATE NOT NULL,
    ano SMALLINT NOT NULL,
    mes SMALLINT NOT NULL,
    salario_nominal DECIMAL(12, 2),
    salario_necessario DECIMAL(12, 2),
    _id_resposta VARCHAR NOT NULL,
    _fonte VARCHAR NOT NULL,
    _requisicao VARCHAR NOT NULL,
    _ingerido_em TIMESTAMPTZ NOT NULL
);
