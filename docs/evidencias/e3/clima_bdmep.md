# Clima pelo BDMEP até a Gold (E3)

O clima chegava só até a Silver, e vazia: a coleta de medições usava a rota
`apitempo.inmet.gov.br/estacao/diaria/...`, que responde 404 (ver
[evidência da E2](../e2/clima.md#diagnostico-e-validacao-da-api-do-inmet)). O PR #22 punha essa
coleta no agendamento diário, o que faria o `clima_job` falhar todo dia. Esta revisão troca a
fonte das medições pelos pacotes anuais do BDMEP, como a própria evidência da E2 recomendava, e
leva o clima até a Gold.

## Fonte: o que foi testado em 2026-11-11

| Rota | Resposta |
|---|---|
| `apitempo.inmet.gov.br/estacoes/T` (catálogo) | 200, 668 estações |
| `apitempo.inmet.gov.br/estacao/diaria/{inicio}/{fim}/{estacao}` | 404 `E_ROUTE_NOT_FOUND` |
| `apitempo.inmet.gov.br/estacao/{inicio}/{fim}/{estacao}` (horária) | 204, corpo vazio, em 2025 e 2026 |
| `apitempo.inmet.gov.br/token/estacao/...` | 200 `CHAVE INVÁLIDA!` (exige token pedido ao INMET) |
| `portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip` | 200; 2006 tem 16 MB, 2025 tem 91 MB; o de 2026 foi atualizado em 2026-11-05 |

Cada pacote traz um CSV horário por estação (`;`, vírgula decimal, latin-1). Três formatos
apareceram na carga, e os três têm teste com trecho real em `tests/fixtures/clima/`:

- **até 2018:** cabeçalho `DATA (YYYY-MM-DD);HORA (UTC)`, ausência como `-9999`;
- **2019:** formato novo, mas com os acentos do cabeçalho de metadados trocados por `?`
  (`DATA DE FUNDAC?O`). A primeira carga falhou nesse ano porque a linha de fundação foi lida
  como cabeçalho. A detecção passou a exigir todas as colunas;
- **desde 2020:** `Data;Hora UTC`, data `2025/01/01`, hora `0000 UTC`, ausência como campo vazio.

## Pipeline

```
portal BDMEP (.zip anual)
  -> bronze.clima: CSV inteiro em clima_resposta (Raw) + resumo por dia UTC em clima_medicao (Delta)
  -> load_clima --tabela medicao: bronze.clima_medicao (DuckDB)
  -> dbt: stg_clima__medicao_diaria -> int_clima__anomalia_mensal -> gold.fct_clima_mensal
```

- **Só o que mudou é baixado.** Cada pacote processado deixa um manifesto (`Last-Modified`,
  tamanho, lista de estações e `VERSAO_LEITURA`) em `clima_resposta`. A coleta seguinte faz um HEAD
  por ano e pula o pacote cujo manifesto já existe.
- **Falha não some.** Pacote de ano encerrado ausente (404), pacote sem nenhuma estação pedida e
  CSV recusado deixam o ano sem manifesto: ele volta na coleta seguinte e o run fica vermelho.
- **Sem vazamento para o treino.** As normais climatológicas usam só os anos anteriores (no
  mínimo 3); os lags são meses de calendário sobre a grade completa; `mes_fechado` marca o mês
  que o INMET ainda não publicou inteiro.

## Carga real (2026-11-11, `data/` local do integrante)

O Delta e o DuckDB de clima anteriores foram copiados para `data/backup-old-lixo/` antes da
carga; nada foi apagado.

| Execução | Resultado |
|---|---|
| 1ª coleta `--medicoes` (2006 a 2026) | 10min37s; 20 anos, 310 CSVs, 105.091 leituras diárias; 2019 falhou (cabeçalho, ver acima) |
| 2ª coleta, com o parser corrigido (`VERSAO_LEITURA` 2) | 21 anos relidos, 0 falhas; 2019 trouxe 5.596 leituras; os outros 20 anos, **0 leituras novas** (as correções não mudaram nenhum valor já gravado) |
| `dagster asset materialize --select '*gold/fct_clima_mensal'` | `RUN_SUCCESS`; `clima_medicoes` em 12 s (21 HEADs, nenhum download), 110.687 linhas em `bronze.clima_medicao`, `check_clima_medicoes_freshness_e_volume` passou, dbt PASS=40 |
| `dbt build` do projeto inteiro (numa cópia do DuckDB) | PASS=277, WARN=0, ERROR=0 |

`silver.stg_clima__medicao_diaria`: 110.687 dias de 16 estações, de 2006-01-01 a 2026-10-31.
`gold.fct_clima_mensal`: 3.881 linhas (praça x mês), 16 praças, de jan/2006 a out/2026;
3.078 com anomalia de temperatura e 2.792 com anomalia de chuva (as outras não têm 3 anos
anteriores do mesmo mês, ou a chuva do mês tem menos de 80% dos dias).

Conferência de sanidade: São Paulo (A701) em set/2024 tem anomalia de **+3,0 °C** e
**−57 mm** de chuva, a seca com onda de calor daquele mês; o choque aparece no mês seguinte em
`temp_media_anomalia_t_menos_1`.

### Cobertura por praça

Cobertura = média de `dias_com_registro / dias_no_mes`.

| Praça | Estação | Meses | Cobertura | Cobertura desde 2024 | Observação |
|---|---|---:|---:|---:|---|
| Brasília | A001 | 250 | 1,00 | 1,00 | |
| Porto Alegre | A801 | 250 | 1,00 | 1,00 | |
| Belo Horizonte | A521 | 241 | 1,00 | 1,00 | começa em out/2006 |
| São Paulo | A701 | 244 | 0,99 | 1,00 | começa em jul/2006 |
| Goiânia | A002 | 250 | 0,99 | 0,91 | |
| Curitiba | A807 | 248 | 0,98 | 1,00 | |
| Grande Vitória | A612 | 241 | 0,98 | 0,94 | começa em out/2006 |
| Campo Grande | A702 | 250 | 0,97 | 1,00 | |
| Rio de Janeiro | A652 | 234 | 0,97 | 0,85 | começa em mai/2007 |
| Salvador | A401 | 245 | 0,97 | 1,00 | |
| São Luís | A203 | 247 | 0,97 | 0,99 | chuva falha (165 meses com chuva) |
| Belém | A201 | 250 | 0,96 | 0,97 | |
| Aracaju | A409 | 238 | 0,88 | 0,96 | último mês: out/2025 |
| Fortaleza | A305 | 223 | 0,88 | 0,49 | fora do catálogo da API; série termina em jan/2025 |
| Recife | A301 | 250 | 0,73 | 0,16 | ausente dos pacotes de 2024 e 2025 |
| Rio Branco | A104 | 220 | 0,69 | 1,00 | começa em jul/2008, com buracos antes de 2024 |

## Limites conhecidos

- **Fortaleza e Recife sem dado recente.** As estações pararam; trocar por outra estação da
  região metropolitana é decisão da Squad (o de-para é o seed
  `dbt/seeds/seed_de_para_estacao_localidade.csv`). Até lá, a Gold mostra o buraco
  (`cobertura_dias = 0`, métricas nulas) e não inventa valor.
- **Uma estação por praça.** A temperatura de uma capital não é a da lavoura que abastece a
  praça. Estações em polos agrícolas podem entrar no de-para sem mudar código: a coleta lê o
  seed e o manifesto muda com a lista.
- **Revisão que volta ao valor anterior.** O `id_medicao` é o hash do conteúdo, então uma leitura
  revisada de A para B e de volta para A fica em B. Corrigir exige tirar a chave primária de
  `bronze.clima_medicao`; ficou registrado em vez de alterado.
- **Dia UTC.** O resumo diário usa o dia UTC, como o BDMEP publica (3 h de diferença para
  Brasília); no grão mensal o efeito é desprezível.
