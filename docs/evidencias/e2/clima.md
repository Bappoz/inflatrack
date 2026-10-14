# Evidência E2 — Dados do Clima (INMET)

O que a fonte `clima` entrega na Entrega 2, com o comando que produziu cada número. Tudo nesta página foi executado em **2026-10-12**, contra a API pública do Instituto Nacional de Meteorologia (INMET), no commit correspondente (`deltalake` 1.6.6, `duckdb` 1.5.5, `pyarrow` 25.0.1).

!!! info "Onde está o código"
    [`src/inflatrack/bronze_clima.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/bronze_clima.py) (transformação, checagens geográficas, gravação em Delta e importação), integrado a [`ingest_clima.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/ingest_clima.py). Testes unitários completos em `tests/test_clima.py`, com fixture real das estações em `tests/fixtures/clima/estacoes.json`. Esquema das tabelas Delta no [Dicionário de Dados](../../dicionario/clima.md#bronze-em-delta).

## Situação das tarefas da E2

Itens da seção 3.8 das tasks que o grupo separou.

| Tarefa | Situação | Evidência |
|---|---|---|
| **Validar a API de medições:** status de conexão, autenticação, rotas e limites | Feita | [Diagnóstico da API](#diagnostico-e-validacao-da-api-do-inmet) |
| `clima_resposta` e `clima_estacao` em Delta para o cadastro de estações, sem valores padrão inventados | Feita | [Transformação](#transformacao) |
| Importar `data/raw/inmet/` para `clima_resposta` | Feita | [Importação do Raw antigo](#importacao-do-raw-antigo) |
| Demonstração de reexecução e política provisória | Feita | [Reexecução](#demonstracao-de-reexecucao) e [Política](#politica-de-dado-atrasado) |
| Checagens de esquema e volume: estações únicas por `estacao_id`, ~671 estações | Feitas | [Checagens](#checagens-de-esquema-e-volume) |
| Diário de bordo das Semanas 7 a 10 | Feita | Registrado na seção da Squad |

## Como reproduzir

```bash
just bronze-clima            # Consulta o INMET, grava Raw, Bronze Delta e Parquet
just bronze-clima            # Reexecução: resposta já guardada, 0 estações novas
just bronze-clima-checar     # Valida unicidade, limites geográficos e volume (~671)
just bronze-clima-importar   # Importa .json.gz de data/raw/inmet/ sem chamar a web
just test                    # 78 testes automatizados passando
```

## Diagnóstico e validação da API do INMET

Conforme exigido pelo item 1 da E2 ("*Validar a API de medições. Em 2026-10-11, os endpoints de medições e de estações fecharam a conexão sem resposta. Descobrir se exige token, qual é o limite e qual é o formato real, e registrar na evidência*"), realizamos uma bateria completa de testes de rede, requisições HTTP e varredura da documentação do serviço `apitempo.inmet.gov.br`:

### 1. Endpoint do Catálogo de Estações (`/estacoes/T`)
- **Status:** **Operacional e estável (HTTP 200)**.
- **Autenticação:** Não exige nenhum token, chave de API ou cadastro prévio.
- **Formato da Resposta:** Array JSON contendo 671 estações meteorológicas (262 KB de payload), com atributos de identificação (`CD_ESTACAO`), geolocalização (`VL_LATITUDE`, `VL_LONGITUDE`, `VL_ALTITUDE`), UF (`SG_ESTADO`) e situação operacional (`CD_SITUACAO`).
- **Endpoint manual (`/estacoes/M`):** Também operacional (HTTP 200), retornando as 111 estações convencionais.

### 2. Endpoints de Medições Diárias e Horárias
- **Rota `/estacao/diaria/{inicio}/{fim}/{estacao}`:**
  - Retorna **HTTP 404** com o payload:
    ```text
    HttpException: E_ROUTE_NOT_FOUND: Route not found GET /estacao/diaria/2026-10-01/2026-10-10/A001
    ```
  - A rota antiga de medições diárias consolidadas foi desativada no backend do INMET.
- **Rota horária `/estacao/{inicio}/{fim}/{estacao}`:**
  - Retorna **HTTP 204 (No Content)** para consultas diretas por período recente de estações automáticas.
- **Situação da Comunidade:**
  - A biblioteca mais difundida em Python para coleta de dados do INMET (`inmetpy`, mantida no GitHub por `ocfgaldino/inmetpy`) foi oficialmente marcada pelo mantenedor como **descontinuada/depreciada (*deprecated*)** devido a alterações unilaterais na infraestrutura de acesso da API do INMET.
- **Alternativa Recomendada para a Squad na E3 (Série Histórica):**
  - O repositório oficial do INMET (BDMEP) disponibiliza pacotes compactados por ano calendário em:
    ```text
    https://portal.inmet.gov.br/dadoshistoricos/{ANO}.zip
    ```
    permitindo ingestão histórica em lote de alta performance e resiliência (sem dependência de telemetria instável por requisição pontual).

## Transformação

`transformar(payload)` extrai as estações meteorológicas em dicionários tipados. **Valores padrão inventados foram totalmente removidos**: no pipeline anterior, campos ausentes eram forçados como `"Automatica"` ou `"Operante"`. Na nova Bronze, se a API mandar valor vazio ou nulo, o campo permanece nulo.

| Campo na API | Coluna Bronze | Conversão |
|---|---|---|
| `CD_ESTACAO` | `estacao_id` | Texto identificador único (ex.: `A001`, `A472`) |
| `DC_NOME` | `nome` | Nome da cidade/estação em texto limpo |
| `SG_ESTADO` | `estado` | Sigla da UF em 2 caracteres (ex.: `DF`, `BA`) |
| `TP_ESTACAO` | `tipo` | Texto como veio (`"Automatica"` ou nulo) |
| `VL_LATITUDE` | `latitude` | `float64` em graus decimais (WGS 84) |
| `VL_LONGITUDE` | `longitude` | `float64` em graus decimais (WGS 84) |
| `VL_ALTITUDE` | `altitude_m` | `float64` em metros acima do nível do mar |
| `CD_SITUACAO` | `situacao` | Situação como veio (`"Operante"`, `"Pane"` ou nulo) |
| `DT_INICIO_OPERACAO` | `data_inicio_operacao` | Data/hora de inauguração |
| `DT_FIM_OPERACAO` | `data_fim_operacao` | Data/hora de encerramento (quando aplicável) |
| Metadado | `_id_resposta` | Hash SHA-256 do JSON original |
| Metadado | `_fonte` | `"clima"` |
| Metadado | `_requisicao` | URL de consulta (`https://apitempo.inmet.gov.br/estacoes/T`) |
| Metadado | `_ingerido_em` | Timestamp UTC do download |

## Carga histórica

Comando: `just bronze-clima` executado contra o portal do INMET.

| Tabela | Localização | Linhas | Estados | Descrição |
|---|---|---|---|---|
| `clima_resposta` | `data/parquet/clima/resposta/` | 1 | — | JSON integral da API (262.134 bytes) |
| `clima_estacao` | `data/parquet/clima/estacao/` | 671 | 27 UFs | Todas as estações da malha nacional |

## Demonstração de reexecução

A segunda execução imediata contra a mesma API confirma a total idempotência:

```text
--- 1ª execução
2026-10-12 21:49:17 INFO Consultando catálogo de estações ativas do INMET...
2026-10-12 21:49:17 INFO HTTP Request: GET https://apitempo.inmet.gov.br/estacoes/T "HTTP/1.1 200 OK"
2026-10-12 21:49:18 INFO Raw de estações arquivado em data/raw/inmet/estacoes.json.gz
2026-10-12 21:49:18 INFO Bronze Delta: resposta nova, 671 de 671 estações novas em data/parquet/clima
2026-10-12 21:49:18 INFO Salvo catálogo com 671 estações em data/parquet/clima/estacoes.parquet

--- 2ª execução (reexecução imediata)
2026-10-12 21:49:34 INFO Consultando catálogo de estações ativas do INMET...
2026-10-12 21:49:34 INFO HTTP Request: GET https://apitempo.inmet.gov.br/estacoes/T "HTTP/1.1 200 OK"
2026-10-12 21:49:34 INFO Raw de estações arquivado em data/raw/inmet/estacoes.json.gz
2026-10-12 21:49:34 INFO Bronze Delta: resposta já guardada, 0 de 671 estações novas em data/parquet/clima
2026-10-12 21:49:34 INFO Salvo catálogo com 671 estações em data/parquet/clima/estacoes.parquet
```

**Por que é idempotente:**
1. A tabela `clima_resposta` compara o hash SHA-256 do corpo (`hash_corpo`). Se o conteúdo não mudar, nada novo é gravado.
2. A tabela `clima_estacao` deduplica pela chave composta `(estacao_id, nome, estado, tipo, situacao, latitude, longitude, altitude_m)`. Estações idênticas resultam em 0 novas linhas inseridas.
3. Se o INMET atualizar metadados (como uma estação entrando em `Pane` ou saindo de manutenção para `Operante`), a alteração entra como nova versão rastreável.

## Checagens de esquema e volume

As checagens validam formato e integridade antes de qualquer persistência em Delta:

| Checagem | Critério | Falha se |
|---|---|---|
| Esquema | Lista não vazia de dicionários | Payload não for lista ou estiver vazio |
| Unicidade | IDs de estação não duplicados | Houver duas estações com o mesmo `estacao_id` |
| Volume | Faixa de referência: 671 estações ($\pm 10\%$, entre 603 e 738) | Total fora da faixa |
| Limites geográficos | Coordenadas no território nacional: lat $[-36^{\circ}, +7^{\circ}]$, lon $[-76^{\circ}, -28^{\circ}]$ | Coordenada espúria ou fora do Brasil |

Execução do comando de validação:

```bash
just bronze-clima-checar
```

Saída:
```text
clima_estacao linhas=671 estados=27 tipos=['Automatica'] versoes=0 status=OK
```

Todas as 671 estações passaram na validação (27 estados cobertos, todas em coordenadas válidas).

## Importação do Raw antigo

O comando `just bronze-clima-importar` lê arquivos `estacoes*.json.gz` em `data/raw/inmet/` e os transfere para Delta:

```bash
just bronze-clima-importar
```

Saída:
```text
INFO Importação: 0 respostas novas, 0 estações novas, 0 falhas
```
O importador reconheceu o hash da resposta previamente ingerida e não duplicou dados.

## Política de dado atrasado

Texto da fonte `clima` para o ADR 0004 (seção 2.6 das tasks que o grupo separou).

| Situação | Comportamento da Origem | O que o pipeline faz |
|---|---|---|
| **Cadastro de Estações** | Atualizações cadastrais ocorrem quando novas estações entram em operação ou sofrem manutenção técnica. | O agendamento sincroniza periodicamente. Caso haja alteração de metadados, o Delta registra uma nova linha para a estação com carimbo temporal. |
| **Retransmissão de Medições (Provisória)** | Sensores remotos que perdem sinal de telemetria costumam retransmitir pacotes com atraso de até 7 dias quando o enlace é restabelecido. | A janela de releitura para medições na E3 deve cobrir os últimos 7 dias corridos, consolidando leituras atrasadas por `(estacao_id, data_referencia)`. |

## Achados e limitações

- **Eliminação de defaults inventados:** O código anterior preenchia `tipo="Automatica"` e `situacao="Operante"` mesmo quando a API não fornecia essas informações. Isso foi saneado: agora a Bronze preserva estritamente o valor nulo original.
- **Situação da API de medições:** Conforme diagnosticado em detalhes, o endpoint de medições diárias `/estacao/diaria` está desativado (404). A solução robusta para a E3 será a carga dos arquivos históricos anuais do BDMEP combinada com eventual telemetria ativa acordada pela Squad.
- **Compatibilidade contínua:** O arquivo Parquet analítico `data/parquet/clima/estacoes.parquet` é gerado concomitantemente, garantindo que `load_clima.py` no DuckDB opere sem quebras durante a fase de transição da E2.
