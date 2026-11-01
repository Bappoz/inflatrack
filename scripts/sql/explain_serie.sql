-- =============================================================================
-- InflaTrack — Evidência de Otimização SQL: EXPLAIN (ANALYZE, BUFFERS)
-- Tabela de Vitrine Analítica: serie.serie_mensal
-- =============================================================================
-- Atende ao requisito da Entrega 3:
-- "Ao menos uma consulta otimizada a partir do plano de execução, com
--  EXPLAIN (ANALYZE, BUFFERS) antes e depois no repositório"
-- =============================================================================

-- 1. Preparação do Schema e Tabela no PostgreSQL
CREATE SCHEMA IF NOT EXISTS serie;

DROP TABLE IF EXISTS serie.serie_mensal CASCADE;

CREATE TABLE serie.serie_mensal (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_fonte              SMALLINT NOT NULL,
    codigo_classificacao  VARCHAR(20) NOT NULL,
    codigo_localidade     INTEGER NOT NULL,
    codigo_variavel       SMALLINT NOT NULL,
    mes_referencia        DATE NOT NULL,
    valor                 NUMERIC(16, 7) NOT NULL,
    ingerido_em           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Geração de Volume de Benchmark Realista (250.000 registros históricos)
INSERT INTO serie.serie_mensal (
    id_fonte,
    codigo_classificacao,
    codigo_localidade,
    codigo_variavel,
    mes_referencia,
    valor
)
SELECT
    7060::smallint,
    CASE (g % 50)
        WHEN 0 THEN '1101002' -- Subitem Arroz
        WHEN 1 THEN '1101001'
        ELSE (1100000 + (g % 50))::text
    END,
    CASE (g % 17)
        WHEN 0 THEN 3304557 -- Rio de Janeiro
        WHEN 1 THEN 3550308 -- São Paulo
        ELSE 1000000 + (g % 17)
    END,
    CASE (g % 4)
        WHEN 0 THEN 63::smallint   -- Variação mensal (%)
        WHEN 1 THEN 2265::smallint -- Acumulado 12m (%)
        ELSE 69::smallint
    END,
    DATE '2010-01-01' + ((g % 150) * INTERVAL '1 month'),
    ROUND((sin(g) * 2.5 + 3.0)::numeric, 4)
FROM generate_series(1, 250000) AS g;

-- Atualiza estatísticas do otimizador de custos (Cost-Based Optimizer - CBO)
VACUUM ANALYZE serie.serie_mensal;

-- -----------------------------------------------------------------------------
-- CENÁRIO 1: Consulta Analítica SEM ÍNDICE (Estado Inicial)
-- -----------------------------------------------------------------------------
-- Consulta do lojista: recupera histórico de variação mensal de um subitem em
-- uma praça específica a partir de 2015, ordenado da mais recente para a mais antiga.
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS)
SELECT mes_referencia, codigo_localidade, codigo_variavel, valor
FROM serie.serie_mensal
WHERE codigo_classificacao = '1101002'
  AND codigo_localidade = 3304557
  AND codigo_variavel = 63
  AND mes_referencia >= '2015-01-01'
ORDER BY mes_referencia DESC;

-- -----------------------------------------------------------------------------
-- CENÁRIO 2: Criação do Índice Cobrindo (Covering B-Tree Index)
-- -----------------------------------------------------------------------------
-- Engenharia de Índices:
-- * Chave do índice composta pelos predicados de igualdade e range + ordenação;
-- * Cláusula INCLUDE (valor) viabiliza Index-Only Scan eliminando acessos à Heap.
CREATE INDEX idx_serie_mensal_covering 
ON serie.serie_mensal (codigo_classificacao, codigo_localidade, codigo_variavel, mes_referencia DESC)
INCLUDE (valor);

VACUUM ANALYZE serie.serie_mensal;

-- -----------------------------------------------------------------------------
-- CENÁRIO 3: Consulta Analítica COM ÍNDICE COBRINDO (Estado Otimizado)
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS)
SELECT mes_referencia, codigo_localidade, codigo_variavel, valor
FROM serie.serie_mensal
WHERE codigo_classificacao = '1101002'
  AND codigo_localidade = 3304557
  AND codigo_variavel = 63
  AND mes_referencia >= '2015-01-01'
ORDER BY mes_referencia DESC;
