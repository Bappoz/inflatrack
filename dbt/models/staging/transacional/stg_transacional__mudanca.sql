-- Uma linha por mudança capturada por CDC, 1:1 com a Bronze. A linha de cada tabela de origem
-- continua em JSON (antes e depois); quem conhece as colunas é o intermediate.

select
    lsn,
    lsn_commit,
    id_transacao,
    tabela,
    operacao,
    id_registro,
    cast(antes as json) as antes,
    cast(depois as json) as depois,
    commit_em,
    _ingerido_em
from {{ source('bronze_transacional', 'transacional_mudanca') }}
