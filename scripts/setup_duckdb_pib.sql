-- Contas Nacionais Trimestrais (SIDRA 1846) no mesmo DuckDB das commodities.
--
-- Por que o mesmo arquivo e não um banco por fonte: a pergunta do InflaTrack
-- cruza fontes ("o comércio encareceu porque o frete subiu?"), e cruzar dentro
-- de um arquivo é um JOIN, enquanto cruzar entre arquivos exige ATTACH em toda
-- sessão e impede FK entre as duas metades. O isolamento que interessa é por
-- tabela e por view, não por arquivo. Ver docs/adr/0002-duckdb-unico.md.

CREATE TABLE IF NOT EXISTS pib_setor (
    codigo VARCHAR PRIMARY KEY,   -- id interno do SIDRA (o mesmo devolvido em D4C)
    nome VARCHAR NOT NULL,
    grupo VARCHAR NOT NULL,       -- 'atividade' | 'demanda' | 'agregado'
    nucleo BOOLEAN NOT NULL       -- entra no recorte de pressão sobre preço
);

CREATE TABLE IF NOT EXISTS pib_valor (
    codigo_setor VARCHAR REFERENCES pib_setor(codigo),
    data_referencia DATE NOT NULL,       -- primeiro dia do trimestre
    ano SMALLINT NOT NULL,
    trimestre TINYINT NOT NULL,
    valor_milhoes_brl DOUBLE NOT NULL,   -- preços correntes, milhões de reais
    PRIMARY KEY (codigo_setor, data_referencia)
);

-- Série longa com as duas leituras que interessam ao lojista: quanto o setor
-- cresceu contra o mesmo trimestre do ano anterior (tira a sazonalidade sem
-- precisar de série dessazonalizada) e quanto ele pesa no PIB.
CREATE OR REPLACE VIEW vw_pib_setor_trimestral AS
WITH pib_total AS (
    SELECT data_referencia, valor_milhoes_brl AS pib
    FROM pib_valor
    WHERE codigo_setor = '90707'   -- PIB a preços de mercado
)
SELECT
    v.data_referencia,
    v.ano,
    v.trimestre,
    s.codigo AS codigo_setor,
    s.nome AS setor,
    s.grupo,
    s.nucleo,
    v.valor_milhoes_brl,
    round(
        100.0 * (v.valor_milhoes_brl - lag(v.valor_milhoes_brl, 4)
            OVER (PARTITION BY s.codigo ORDER BY v.data_referencia))
        / nullif(lag(v.valor_milhoes_brl, 4)
            OVER (PARTITION BY s.codigo ORDER BY v.data_referencia), 0),
        2
    ) AS var_anual_pct,
    round(100.0 * v.valor_milhoes_brl / nullif(t.pib, 0), 2) AS participacao_pib_pct
FROM pib_valor v
JOIN pib_setor s ON s.codigo = v.codigo_setor
LEFT JOIN pib_total t ON t.data_referencia = v.data_referencia;

-- O recorte de indicadores com efeito mais direto no preço ao consumidor.
CREATE OR REPLACE VIEW vw_pib_nucleo AS
SELECT * FROM vw_pib_setor_trimestral WHERE nucleo;

-- Formato largo, uma linha por trimestre — espelha vw_features_daily e
-- vw_features_monthly das commodities, para alimentar o mesmo tipo de modelo.
CREATE OR REPLACE VIEW vw_features_pib_trimestral AS
SELECT
    data_referencia,
    ano,
    trimestre,
    max(valor_milhoes_brl) FILTER (codigo_setor = '90707') AS pib,
    max(valor_milhoes_brl) FILTER (codigo_setor = '90687') AS agropecuaria,
    max(valor_milhoes_brl) FILTER (codigo_setor = '90695') AS eletricidade_gas,
    max(valor_milhoes_brl) FILTER (codigo_setor = '90696') AS servicos,
    max(valor_milhoes_brl) FILTER (codigo_setor = '90697') AS comercio,
    max(valor_milhoes_brl) FILTER (codigo_setor = '90698') AS transporte,
    max(valor_milhoes_brl) FILTER (codigo_setor = '90700') AS atividades_financeiras,
    max(valor_milhoes_brl) FILTER (codigo_setor = '90706') AS impostos_sobre_produtos,
    max(valor_milhoes_brl) FILTER (codigo_setor = '93404') AS consumo_familias,
    max(valor_milhoes_brl) FILTER (codigo_setor = '93405') AS consumo_administracao_publica,
    max(valor_milhoes_brl) FILTER (codigo_setor = '93407') AS exportacao,
    max(valor_milhoes_brl) FILTER (codigo_setor = '93408') AS importacao
FROM vw_pib_nucleo
GROUP BY data_referencia, ano, trimestre;
