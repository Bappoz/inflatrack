# El Niño / La Niña (RONI, NOAA)

Este documento registra as características arquiteturais e de negócio do índice de El Niño e La
Niña usado como variável climática global do modelo preditivo.

## Série coletada

| Série | Indicador | Unidade | Frequência |
|---|---|---|---|
| [RONI](https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt) | *Relative Oceanic Niño Index*: anomalia da temperatura da superfície do mar na região Niño 3.4 (5°N–5°S, 120°W–170°W), em média móvel de 3 meses, descontada da média da faixa tropical | °C | Mensal (temporadas de 3 meses sobrepostas: DJF, JFM, ..., NDJ) |

**Por que o RONI e não o ONI.** O NOAA adotou o RONI no início de 2026 no lugar do ONI: ao
descontar o aquecimento médio dos trópicos, ele é menos afetado pelo aquecimento global na
identificação dos eventos. O Banco Central passou a usá-lo no Relatório de Política Monetária de
setembro de 2026 (boxe "Efeito dos eventos El Niño e La Niña sobre a produtividade das principais
lavouras brasileiras").

**Por que entra no projeto.** O clima das praças e dos polos agrícolas mede o que já aconteceu
em cada lugar; o RONI antecipa o padrão regional. O El Niño costuma trazer chuva acima da média no
Sul e seca no Norte e Nordeste, e a La Niña, o padrão oposto. O Banco Central estimou que o El
Niño forte de 2015–16 contribuiu com cerca de 11 p.p. para a inflação de alimentos
([Estudo Especial 57](https://www.bcb.gov.br/conteudo/relatorioinflacao/EstudosEspeciais/EE057_Impactos_do_clima_na_inflacao_de_alimentos.pdf)),
e que o efeito sobre a produtividade aparece 9 a 16 meses antes de dezembro do ano da colheita.

---

## 1. Fonte de Origem

| Atributo | Resposta |
| :--- | :--- |
| **Nome da fonte** | NOAA Climate Prediction Center: RONI |
| **Tipo** | Terceiro |
| **Quem ou o que gera** | National Oceanic and Atmospheric Administration (EUA) |
| **O que essa fonte contém** | Uma linha por temporada de 3 meses desde DJF/1950: temporada, ano do mês central e anomalia em °C |
| **Formato em que chega** | Texto (`SEAS YR ANOM`, colunas separadas por espaço), arquivo único com a série inteira |
| **Volume estimado** | ~920 linhas, ~15 KB; cresce 1 linha por mês |
| **Frequência de chegada** | Mensal, no começo do mês seguinte ao último mês da temporada |
| **Vazão** | Baixa |
| **Pureza** | Alta (sem lacunas nem valores sentinela; a Bronze recusa buraco ou valor fora de ±4 °C) |
| **Previsibilidade do formato** | Alta |
| **Contém dado pessoal?** | Não |
| **Base legal LGPD** | Não se aplica |
| **Retenção** | Permanente |
| **O que quebra se essa fonte falhar** | `gold.fct_enso_mensal` para de avançar; o modelo preditivo perde o sinal de El Niño / La Niña dos meses recentes. O histórico já carregado não é afetado. |

## 2. Conjunto de Dados / Armazenamento

| Atributo | Resposta |
| :--- | :--- |
| **Raw** | `enso_resposta` em Delta (`data/parquet/enso/resposta/`): o `.txt` inteiro, uma linha por conteúdo diferente (SHA-256) |
| **Bronze** | `enso_roni` em Delta (`data/parquet/enso/roni/`) e `bronze.enso_roni` no DuckDB: uma linha por versão de valor de temporada |
| **Silver** | `silver.stg_enso__roni`: uma linha por mês central, com a revisão mais recente |
| **Gold** | `gold.fct_enso_mensal`: RONI, fase, intensidades no formato do BCB e lags de 3 a 12 meses |

## 3. Carga de trabalho

### Taxa de escrita

- **Carga histórica e regime:** cada coleta baixa a série inteira (~15 KB). O `enso_job` roda toda segunda-feira às 9h; o `popular_banco_job` o inclui na primeira carga.
- **Revisões:** o NOAA recalcula valores antigos quando muda a climatologia. Como o id da linha é o hash de (temporada, ano, valor), a revisão entra como linha nova e a anterior fica; reexecutar sem mudança não grava nada.
- **Checagens antes de gravar:** cabeçalho `SEAS YR ANOM`, temporadas conhecidas, nenhum buraco nem mês repetido, valores entre -4 e 4 °C, pelo menos 900 temporadas. Arquivo que falha não grava nada.

### Execução

- `uv run python -m inflatrack.bronze.enso coletar` e `uv run python -m inflatrack.loaders.load_enso`.
- No Dagster: `enso_parquet` → `enso_duckdb` (grupo `enso`), com o check `check_enso_freshness_e_volume` (110 dias, 900 temporadas).

## 4. Restrições que a origem impõe

- **Média centrada:** o valor do mês central m usa o mês m+1 (ASO = agosto, setembro e outubro) e só é publicado no começo de m+2. Usar o RONI de setembro para prever setembro seria usar outubro: vazamento. A Gold traz `mes_publicacao` (m + 2 meses), e os lags de 3 a 12 meses já respeitam o atraso.
- **Classificação oficial de episódio:** o NOAA declara El Niño ou La Niña quando o índice fica além de ±0,5 °C por 5 temporadas seguidas, o que depende de temporadas futuras. A Gold usa só o limiar do mês (`fase_limiar`) e as intensidades contínuas, como o Banco Central.
- **Recorte:** a série começa em 1950, mas `gold.fct_enso_mensal` vai de jan/1979 (início da `dim_calendario`); os lags dos primeiros meses usam 1978.
