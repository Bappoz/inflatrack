-- 0006 — Clima na vitrine: cópias de gold.fct_clima_mensal, gold.fct_clima_polo_mensal e
-- gold.fct_enso_mensal no schema `serie`, para o painel de clima do Metabase.
--
-- Mesmas regras da 0005: quem preenche é inflatrack.reverse_etl.exportar_serie, que apaga e insere
-- SEM recriar a tabela; as colunas estão na mesma ordem dos modelos do dbt (se divergirem, a cópia
-- falha sem alterar nada); fatos sem chave primária, porque o grão é testado na Gold.
--
-- Reexecutável: tudo é `if not exists`. Num volume existente: `just migrar 0006_serie_clima.sql`.

begin;

-- Clima por praça do IPCA x mês. Dado público.
create table if not exists serie.fct_clima_mensal (
    codigo_localidade                  integer,
    mes_referencia                     date,
    mes_fechado                        boolean,
    estacoes_com_dado                  bigint,
    dias_com_registro                  bigint,
    dias_provisorios                   bigint,
    dias_no_mes                        bigint,
    cobertura_dias                     numeric(5, 4),
    temp_media                         numeric(8, 3),
    temp_min_absoluta                  numeric(8, 3),
    temp_max_absoluta                  numeric(8, 3),
    temp_media_anomalia                numeric(8, 3),
    temp_media_mm3                     numeric(8, 3),
    temp_media_t_menos_1               numeric(8, 3),
    temp_media_t_menos_2               numeric(8, 3),
    temp_media_t_menos_3               numeric(8, 3),
    temp_media_anomalia_t_menos_1      numeric(8, 3),
    temp_media_anomalia_t_menos_2      numeric(8, 3),
    temp_media_anomalia_t_menos_3      numeric(8, 3),
    precipitacao_total_mm              numeric(10, 3),
    precipitacao_anomalia_mm           numeric(10, 3),
    dias_com_chuva                     numeric(5, 2),
    precipitacao_t_menos_1             numeric(10, 3),
    precipitacao_t_menos_2             numeric(10, 3),
    precipitacao_t_menos_3             numeric(10, 3),
    precipitacao_anomalia_t_menos_1    numeric(10, 3),
    precipitacao_anomalia_t_menos_2    numeric(10, 3),
    precipitacao_anomalia_t_menos_3    numeric(10, 3),
    precipitacao_3m_mm                 numeric(10, 3),
    spi_3                              numeric(6, 3),
    spi_3_t_menos_1                    numeric(6, 3),
    spi_3_t_menos_2                    numeric(6, 3),
    spi_3_t_menos_3                    numeric(6, 3),
    umidade_relativa_media_pct         numeric(8, 3)
);
comment on table serie.fct_clima_mensal is
    'Uma linha por praça do IPCA x mês. Cópia de gold.fct_clima_mensal.';
create index if not exists fct_clima_mensal_consulta_idx
    on serie.fct_clima_mensal (codigo_localidade, mes_referencia desc);

-- Clima por polo agrícola x mês. Dado público.
create table if not exists serie.fct_clima_polo_mensal (
    estacao_id                         text,
    polo                               text,
    uf                                 text,
    culturas                           text,
    mes_referencia                     date,
    mes_fechado                        boolean,
    dias_com_registro                  bigint,
    dias_provisorios                   bigint,
    dias_no_mes                        bigint,
    cobertura_dias                     numeric(5, 4),
    temp_media                         numeric(8, 3),
    temp_min_absoluta                  numeric(8, 3),
    temp_max_absoluta                  numeric(8, 3),
    temp_media_anomalia                numeric(8, 3),
    temp_media_mm3                     numeric(8, 3),
    temp_media_t_menos_1               numeric(8, 3),
    temp_media_t_menos_2               numeric(8, 3),
    temp_media_t_menos_3               numeric(8, 3),
    temp_media_anomalia_t_menos_1      numeric(8, 3),
    temp_media_anomalia_t_menos_2      numeric(8, 3),
    temp_media_anomalia_t_menos_3      numeric(8, 3),
    precipitacao_total_mm              numeric(10, 3),
    precipitacao_anomalia_mm           numeric(10, 3),
    dias_com_chuva                     numeric(5, 2),
    precipitacao_t_menos_1             numeric(10, 3),
    precipitacao_t_menos_2             numeric(10, 3),
    precipitacao_t_menos_3             numeric(10, 3),
    precipitacao_anomalia_t_menos_1    numeric(10, 3),
    precipitacao_anomalia_t_menos_2    numeric(10, 3),
    precipitacao_anomalia_t_menos_3    numeric(10, 3),
    precipitacao_3m_mm                 numeric(10, 3),
    spi_3                              numeric(6, 3),
    spi_3_t_menos_1                    numeric(6, 3),
    spi_3_t_menos_2                    numeric(6, 3),
    spi_3_t_menos_3                    numeric(6, 3),
    umidade_relativa_media_pct         numeric(8, 3)
);
comment on table serie.fct_clima_polo_mensal is
    'Uma linha por polo agrícola (estação do INMET) x mês. Cópia de gold.fct_clima_polo_mensal.';

-- El Niño / La Niña (RONI) por mês. Dado público.
create table if not exists serie.fct_enso_mensal (
    mes_referencia                     date primary key,
    mes_publicacao                     date,
    temporada                          text,
    roni                               numeric(5, 2),
    fase_limiar                        text,
    intensidade_el_nino                numeric(5, 2),
    intensidade_la_nina                numeric(5, 2),
    roni_t_menos_3                     numeric(5, 2),
    intensidade_el_nino_t_menos_3      numeric(5, 2),
    intensidade_la_nina_t_menos_3      numeric(5, 2),
    roni_t_menos_6                     numeric(5, 2),
    intensidade_el_nino_t_menos_6      numeric(5, 2),
    intensidade_la_nina_t_menos_6      numeric(5, 2),
    roni_t_menos_9                     numeric(5, 2),
    intensidade_el_nino_t_menos_9      numeric(5, 2),
    intensidade_la_nina_t_menos_9      numeric(5, 2),
    roni_t_menos_12                    numeric(5, 2),
    intensidade_el_nino_t_menos_12     numeric(5, 2),
    intensidade_la_nina_t_menos_12     numeric(5, 2)
);
comment on table serie.fct_enso_mensal is
    'Uma linha por mês central da temporada do RONI. Cópia de gold.fct_enso_mensal.';

-- Mesmas permissões das outras tabelas públicas de `serie` (0005).
grant select, insert, delete on serie.fct_clima_mensal, serie.fct_clima_polo_mensal,
    serie.fct_enso_mensal to inflatrack_pipeline;
grant select on serie.fct_clima_mensal, serie.fct_clima_polo_mensal, serie.fct_enso_mensal
    to metabase_leitor, lojista_app;

commit;
