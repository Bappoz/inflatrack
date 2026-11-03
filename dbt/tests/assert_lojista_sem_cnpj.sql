-- LGPD: o CNPJ em texto aberto nunca chega à Bronze nem às camadas seguintes. Procura a chave do
-- JSON e qualquer sequência de 14 dígitos; o hash tem 64 caracteres hexadecimais em sequência,
-- então o limite de palavra evita o falso positivo.
select lsn, tabela
from {{ source('bronze_transacional', 'transacional_mudanca') }}
where coalesce(antes, '') || coalesce(depois, '') like '%"cnpj"%'
    or coalesce(antes, '') || coalesce(depois, '') like '%nome_fantasia%'
    or regexp_matches(coalesce(antes, '') || coalesce(depois, ''), '\b[0-9]{14}\b')
