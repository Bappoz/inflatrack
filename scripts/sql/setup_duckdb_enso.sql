-- ENSO (El Niño / La Niña): RONI do NOAA, espelho da tabela Delta enso_roni.
-- Uma linha por versão de valor de temporada; a staging usa a mais recente de cada mês.
CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.enso_roni (
    id_leitura VARCHAR PRIMARY KEY,
    temporada VARCHAR NOT NULL,
    ano SMALLINT NOT NULL,
    mes_referencia DATE NOT NULL,
    roni DOUBLE NOT NULL,
    _id_resposta VARCHAR NOT NULL,
    _fonte VARCHAR NOT NULL,
    _requisicao VARCHAR NOT NULL,
    _ingerido_em TIMESTAMPTZ NOT NULL
);
