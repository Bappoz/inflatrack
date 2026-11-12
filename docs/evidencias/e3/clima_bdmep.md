# Clima pelo BDMEP até a Gold (E3)

O clima chegava só até a Silver, e vazia: a coleta de medições usava a rota
`apitempo.inmet.gov.br/estacao/diaria/...`, que responde 404 (ver
[evidência da E2](../e2/clima.md#diagnostico-e-validacao-da-api-do-inmet)). O PR #22 punha essa
coleta no agendamento diário, o que faria o `clima_job` falhar todo dia. Esta revisão troca a
fonte das medições pelos pacotes anuais do BDMEP, como a própria evidência da E2 recomendava, e
leva o clima até a Gold. Como o BDMEP chega com até ~1 mês de atraso, os dias ainda não
publicados são cobertos por um clima **provisório** do Open-Meteo (ver
[abaixo](#clima-provisorio-open-meteo)).

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
anteriores do mesmo mês, ou a chuva do mês tem menos de 80% dos dias; a regra depois passou a ser
a 3/5 da OMM, ver [fonte do clima](../../fontes/clima.md#5-modelo-mensal-e-vinculo-com-o-ipca)).

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

## Clima provisório (Open-Meteo)

Pesquisa de 2026-11-11 por fonte gratuita do clima do dia:

| Fonte | Acesso | Até quando | Decisão |
|---|---|---|---|
| Open-Meteo (`archive-api`) | grátis, sem chave, não comercial, CC BY 4.0 | até ontem | **usada** como provisório |
| NASA POWER | grátis, sem chave | ~3 dias de atraso (até 08/11 em 11/11) | não usada: mais atraso, grade mais grossa |
| INMET com token | grátis, por e-mail a `cadastro.act@inmet.gov.br` | até ontem, medido | melhor opção quando houver token |
| NOAA GHCN-Daily | grátis | estações do Brasil paradas nos anos 1990 | descartada |

O Open-Meteo é **modelo em grade**, não estação. Contra o medido em Brasília (A001), de nov/2025
a out/2026, a temperatura média mensal ficou de 0,1 a 0,7 °C acima em todos os meses. A chuva
divergiu muito: 275 mm medidos contra 134 mm do modelo em nov/2025, e 79 contra 204 em fev/2026.
Por isso o provisório fica à parte e é trocado pelo oficial.

| Regra | Onde |
|---|---|
| Janela: do dia seguinte ao último oficial até ontem (dia UTC), no máximo 92 dias; sem dado oficial, nada | `janela_provisoria` em `bronze/clima.py` |
| Uma chamada para as 16 estações; coordenadas do cabeçalho do CSV do BDMEP, no seed de-para | `clients/open_meteo.py`, `seed_de_para_estacao_localidade` |
| JSON no Raw (`clima_resposta`); linhas em Delta e DuckDB **separadas** do oficial | `medicao_provisoria/`, `bronze.clima_medicao_provisoria` |
| A staging só usa o provisório depois do último dia oficial; o oficial sempre vence | `stg_clima__medicao_diaria` (`fonte`, `observado`) |
| Gold conta `dias_provisorios`; `mes_fechado` olha só o oficial | `fct_clima_mensal` |
| Check de frescura: 5 dias, mínimo 16 leituras | `check_clima_provisorio_freshness_e_volume` |

**Execução real (2026-11-11, dados locais):**

| Execução | Resultado |
|---|---|
| `dagster job execute -j clima_job` | `RUN_SUCCESS`; catálogo com 678 estações, BDMEP com 21 anos sem mudança, Open-Meteo de 01/11 a 10/11/2026 com 160 leituras (16 estações x 10 dias), os 3 checks de clima passando |
| `dagster asset materialize --select '*gold/fct_clima_mensal'` | `RUN_SUCCESS`, dbt PASS=47; a releitura do Open-Meteo não trouxe linha nova |
| Conferência | 0 dia provisório em data já publicada pelo INMET (até 31/10); nov/2026 na Gold com 16 praças, `dias_provisorios = 10` e `mes_fechado = false` |

Achado durante a execução: o seed de-para ganhou `latitude` e `longitude`, e o `dbt seed` falhava
num banco que já tinha a tabela com as 3 colunas antigas (o dbt reaproveita a tabela sem
`--full-refresh`). O seed passou a ter `full_refresh: true`, e o teste de build cria antes a
tabela antiga para não deixar o erro voltar.

## Polos agrícolas, SPI-3 e RONI (2026-11-11 e 12)

Depois da pesquisa sobre como se analisa clima para safras (boletim Conab/INMET, ZARC da Embrapa,
estudos do Banco Central), entraram as três prioridades: estações nos polos produtores, o índice de
seca SPI-3 e o RONI (El Niño / La Niña). Regras em [fonte do clima](../../fontes/clima.md#6-polos-agricolas-e-seca-de-3-meses-spi-3)
e [fonte ENSO](../../fontes/enso.md).

| Execução nos dados locais (Dagster) | Resultado |
|---|---|
| `clima_job` com as 30 estações | `RUN_SUCCESS`; o manifesto mudou com a lista de estações e os 21 pacotes foram relidos uma vez (11 min): 286 CSVs e 96.375 leituras novas, 207.062 no total; Open-Meteo para as 30 estações; 3 checks passando |
| `enso_job` | `RUN_SUCCESS`; 921 temporadas (DJF/1950 a ASO/2026); check passando |
| Gold (`fct_clima_mensal`, `fct_clima_polo_mensal`, `fct_enso_mensal`) | `RUN_SUCCESS`, dbt PASS=92 |

**Polos.** 14 polos de 2006–2008 a out/2026, cobertura média de 0,82 (Sorriso) a 1,00 (Irecê).

**SPI-3.** Começa em ago/2016 (10 anos anteriores). Nos polos, média -0,05 e desvio 1,24 (o
esperado é 0 e 1; as referências de 10 a 20 anos alargam a distribuição). Sorriso e Dourados têm
poucos meses com SPI (15 e 18): falhas de chuva frequentes quebram a janela de 3 meses pela regra
3/5. Conferência: set/2024 marca seca extrema em Unaí (SPI -3,0) e severa em Patrocínio (-1,7) e
Varginha (-1,6), a seca histórica do Cerrado e do Sul de Minas naquele ano.

**RONI.** `gold.fct_enso_mensal` de jan/1979 a set/2026 (573 meses). O maior valor é jan/1983
(+2,40, o El Niño de 1982–83); set/2026 está em +1,97 (El Niño, intensidade 1,47 no formato do
Banco Central), publicado em nov/2026.

## Limites conhecidos

- **Fortaleza e Recife sem dado recente.** As estações pararam; trocar por outra estação da
  região metropolitana é decisão da Squad (o de-para é o seed
  `dbt/seeds/seed_de_para_estacao_localidade.csv`). Até lá, a Gold mostra o buraco
  (`cobertura_dias = 0`, métricas nulas) e não inventa valor.
- **Uma estação por praça e por polo.** O Paraná, segundo produtor de grãos, ficou sem polo por
  falta de estação automática com série boa. Para incluir outra estação, basta acrescentá-la ao
  seed de polos; a coleta lê o seed e o manifesto muda com a lista.
- **Revisão que volta ao valor anterior.** O `id_medicao` é o hash do conteúdo, então uma leitura
  revisada de A para B e de volta para A fica em B. Corrigir exige tirar a chave primária de
  `bronze.clima_medicao`; ficou registrado em vez de alterado.
- **Provisório é modelo.** A chuva do Open-Meteo não deve entrar no treino; o `mes_fechado`
  já tira esses meses. Quando a Squad tiver o token do INMET, o provisório pode passar a vir
  da medição das próprias estações, mudando só o cliente.
- **Dia UTC.** O resumo diário usa o dia UTC, como o BDMEP publica (3 h de diferença para
  Brasília); no grão mensal o efeito é desprezível.
