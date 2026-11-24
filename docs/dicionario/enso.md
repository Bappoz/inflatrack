# El Niño / La Niña (RONI, NOAA)

Tabelas da fonte ENSO. Origem e regras em [fonte ENSO](../fontes/enso.md).

## Bronze em Delta

### enso_resposta

O arquivo `RONI.ascii.txt` do NOAA na íntegra, uma linha por conteúdo diferente.

| Campo | Tipo | Descrição |
|---|---|---|
| `id_resposta`, `hash_corpo` | string | SHA-256 do texto |
| `_requisicao` | string | URL do NOAA |
| `_ingerido_em` | timestamp (UTC) | Momento do download |
| `corpo` | string | O texto original |

### enso_roni (e `bronze.enso_roni`)

| Campo | Tipo | Descrição |
|---|---|---|
| `id_leitura` | string | SHA-256 de (temporada, ano, valor): uma revisão do NOAA vira linha nova |
| `temporada` | string | `DJF`, `JFM`, ..., `NDJ` |
| `ano` | smallint | Ano do mês central (NDJ de 1950 = nov/1950 a jan/1951) |
| `mes_referencia` | date | Mês central da temporada, dia 1 |
| `roni` | double | Anomalia em °C |
| `_id_resposta`, `_fonte`, `_requisicao`, `_ingerido_em` | — | Procedência |

## Silver: `silver.stg_enso__roni`

Uma linha por `mes_referencia`, com a revisão mais recente (`_ingerido_em` mais novo).

## Gold: `gold.fct_enso_mensal`

Uma linha por mês, de jan/1979 até o último mês central publicado. Global: junta-se a qualquer
fato por `mes_referencia`.

| Campo | Descrição |
|---|---|
| `mes_referencia` | Mês central da temporada (FK para `dim_calendario`) |
| `mes_publicacao` | `mes_referencia` + 2 meses: o primeiro mês em que o valor existe. Para prever o mês t, use só linhas e lags com `mes_publicacao` ≤ t |
| `temporada`, `roni` | A temporada e o índice (°C) |
| `fase_limiar` | `el_nino` (> 0,5), `la_nina` (< -0,5) ou `neutro`, só pelo valor do mês |
| `intensidade_el_nino` | RONI - 0,5 quando RONI > 0,5; senão 0 (formato do Banco Central) |
| `intensidade_la_nina` | \|RONI\| - 0,5 quando RONI < -0,5; senão 0 |
| `roni_t_menos_k`, `intensidade_el_nino_t_menos_k`, `intensidade_la_nina_t_menos_k` | Os mesmos valores k = 3, 6, 9 e 12 meses antes |
