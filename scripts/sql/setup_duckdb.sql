CREATE TABLE IF NOT EXISTS commodity (
    symbol VARCHAR PRIMARY KEY,
    name VARCHAR,
    category VARCHAR,
    unit VARCHAR
);

CREATE TABLE IF NOT EXISTS commodity_cotacao (
    symbol VARCHAR REFERENCES commodity(symbol),
    data_referencia DATE NOT NULL,
    preco DOUBLE NOT NULL,
    PRIMARY KEY (symbol, data_referencia)
);

CREATE OR REPLACE VIEW vw_features_daily AS 
PIVOT (
    SELECT * FROM commodity_cotacao 
    WHERE symbol IN ('WTI', 'BRENT', 'NATURAL_GAS')
) 
ON symbol IN ('WTI', 'BRENT', 'NATURAL_GAS')
USING avg(preco);

CREATE OR REPLACE VIEW vw_features_monthly AS 
PIVOT (
    SELECT * FROM commodity_cotacao 
    WHERE symbol IN ('WHEAT', 'CORN', 'COTTON', 'SUGAR', 'COFFEE', 'ALL_COMMODITIES')
) 
ON symbol IN ('WHEAT', 'CORN', 'COTTON', 'SUGAR', 'COFFEE', 'ALL_COMMODITIES')
USING avg(preco);
