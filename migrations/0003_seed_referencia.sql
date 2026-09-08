-- 0003 — Semente das tabelas de referência pequenas e estáveis.
-- Códigos e períodos conferidos em servicodados.ibge.gov.br/api/v3/agregados/{id}/metadados
-- e em apisidra.ibge.gov.br (consultado em 2026-09-08).
-- A cesta (classificacao / classificacao_versao) NÃO é semeada aqui: vem da
-- ingestão, porque são ~460 categorias por fonte e elas mudam entre as fontes.

begin;

insert into fonte_agregado (id, indice, nome, periodo_inicio, periodo_fim, tem_acum_12m) values
    (2938, 'IPCA', 'IPCA - variação mensal, acumulada no ano e peso mensal',            '2006-07-01', '2011-12-01', false),
    (1419, 'IPCA', 'IPCA - variação mensal, no ano, em 12 meses e peso mensal',         '2012-01-01', '2019-12-01', true),
    (7060, 'IPCA', 'IPCA - variação mensal, no ano, em 12 meses e peso mensal',         '2020-01-01', null,         true),
    (7063, 'INPC', 'INPC - variação mensal, no ano, em 12 meses e peso mensal',         '2020-01-01', null,         true),
    (1737, 'IPCA', 'IPCA - série histórica com número-índice (base dez/1993 = 100)',    '1979-12-01', null,         true);

insert into variavel (codigo, nome, unidade) values
    (  63, 'IPCA - Variação mensal',                                 '%'),
    (  69, 'IPCA - Variação acumulada no ano',                       '%'),
    (2263, 'IPCA - Variação acumulada em 3 meses',                   '%'),
    (2264, 'IPCA - Variação acumulada em 6 meses',                   '%'),
    (2265, 'IPCA - Variação acumulada em 12 meses',                  '%'),
    (  66, 'IPCA - Peso mensal',                                     '%'),
    (2266, 'IPCA - Número-índice (base: dezembro de 1993 = 100)',    'Número-índice'),
    (  44, 'INPC - Variação mensal',                                 '%'),
    (  68, 'INPC - Variação acumulada no ano',                       '%'),
    (2292, 'INPC - Variação acumulada em 12 meses',                  '%'),
    (  45, 'INPC - Peso mensal',                                     '%');

-- 17 localidades a partir de 2012. A tabela 2938 (2006-2011) cobre só 12:
-- não tem Grande Vitória, Rio Branco, São Luís, Aracaju nem Campo Grande.
-- Consulta regional que atravessa 2011/2012 devolve série truncada se isso for ignorado.
insert into localidade (codigo_ibge, nome, tipo, uf) values
    (      1, 'Brasil',            'pais',                 null),
    (   1501, 'Belém',             'regiao_metropolitana', 'PA'),
    (   2301, 'Fortaleza',         'regiao_metropolitana', 'CE'),
    (   2601, 'Recife',            'regiao_metropolitana', 'PE'),
    (   2901, 'Salvador',          'regiao_metropolitana', 'BA'),
    (   3101, 'Belo Horizonte',    'regiao_metropolitana', 'MG'),
    (   3201, 'Grande Vitória',    'regiao_metropolitana', 'ES'),
    (   3301, 'Rio de Janeiro',    'regiao_metropolitana', 'RJ'),
    (   3501, 'São Paulo',         'regiao_metropolitana', 'SP'),
    (   4101, 'Curitiba',          'regiao_metropolitana', 'PR'),
    (   4301, 'Porto Alegre',      'regiao_metropolitana', 'RS'),
    (1200401, 'Rio Branco',        'municipio',            'AC'),
    (2111300, 'São Luís',          'municipio',            'MA'),
    (2800308, 'Aracaju',           'municipio',            'SE'),
    (5002704, 'Campo Grande',      'municipio',            'MS'),
    (5208707, 'Goiânia',           'municipio',            'GO'),
    (5300108, 'Brasília',          'municipio',            'DF');

commit;
