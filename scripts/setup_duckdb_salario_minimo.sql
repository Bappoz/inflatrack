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
