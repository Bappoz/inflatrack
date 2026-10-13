# Evidência E2 — Macroeconomia (Dólar Comercial e Taxa Selic)

O que a frente de **Macroeconomia** (Dólar Comercial e Taxa Selic do Banco Central) entrega na Entrega 2, com os comandos que produziram cada resultado e medição. Tudo nesta página foi executado contra as APIs públicas do BCB (Olinda e SGS) e contra as tabelas Delta Lake locais (`deltalake` 1.6.6, `duckdb` 1.5.5, `pyarrow` 25.0.1).

!!! info "Onde está o código"
    * **Dólar:** [`src/inflatrack/bronze_dolar.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/bronze_dolar.py), integrado a [`src/inflatrack/ingest_dolar.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/ingest_dolar.py). Testes em [`tests/test_bronze_dolar.py`](https://github.com/Bappoz/inflatrack/blob/main/tests/test_bronze_dolar.py) com fixtures em `tests/fixtures/dolar/`.
    * **Selic:** [`src/inflatrack/bronze_selic.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/bronze_selic.py), integrado a [`src/inflatrack/ingest_selic.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/ingest_selic.py). Testes em [`tests/test_bronze_selic.py`](https://github.com/Bappoz/inflatrack/blob/main/tests/test_bronze_selic.py) com fixtures em `tests/fixtures/selic/`.

---

## Situação das tarefas da E2

Tarefas das seções 3.2 e 3.3 do plano de trabalho da Entrega 2.

| Tarefa | Situação | Evidência |
|---|---|---|
| Gravar `dolar_resposta` e `dolar_boletim` em Delta Lake | Feita | [Esquema e Carga do Dólar](#transformacao-e-esquema-bronze) |
| Preservar todos os boletins intradiários (`tipo_boletim`) | Feita | [Preservação de Boletins](#transformacao-e-esquema-bronze) |
| Gravar `selic_resposta` e `selic_taxa_dia` em Delta Lake | Feita | [Esquema e Carga da Selic](#transformacao-e-esquema-bronze) |
| Taxa da Selic apenas tipada, sem forward fill na Bronze | Feita | [Conformidade da Selic](#transformacao-e-esquema-bronze) |
| Demonstração de reexecução e idempotência estrita | Feita | [Demonstração de Reexecução](#demonstracao-de-reexecucao) |
| Política de dado atrasado declarada | Feita | [Política de Dado Atrasado](#politica-de-dado-atrasado) |
| Checagens de esquema, volume e sanidade | Feitas | [Checagens de Sanidade](#checagens-de-esquema-e-volume) |
| Importação de raw legado (se existente) | Feita | [Importação do Raw](#como-reproduzir) |

---

## Como reproduzir

Todas as operações são executadas de forma simples via `just`:

```bash
# 1. Coleta histórica completa das duas fontes (Dólar e Selic de 2020 até hoje)
just bronze-macro

# 2. Reexecução imediata para demonstrar idempotência (0 linhas novas)
just bronze-macro

# 3. Verificação de integridade, sanidade e contagens
just bronze-dolar-checar
just bronze-selic-checar

# 4. Importação de dados brutos antigos (.json.gz legados, se existirem)
just bronze-dolar-importar
just bronze-selic-importar

# 5. Execução dos testes automatizados com Pytest
uv run pytest tests/test_bronze_dolar.py tests/test_bronze_selic.py -v
```

---

## Transformação e Esquema Bronze

A camada Bronze do Banco Central mantém quatro tabelas Delta em formato aberto sobre Parquet, particionadas por ano (`ano`):

### 1. Dólar Comercial (API Olinda PTAX)

* `data/parquet/dolar/resposta/`: Tabela `dolar_resposta` contendo o payload OData integral da API, com hash SHA-256 (`hash_corpo`) que assegura idempotência na ingestão.
* `data/parquet/dolar/boletim/`: Tabela `dolar_boletim` preservando **todos os boletins publicados** no dia (`Abertura`, `Intermediário`, `Fechamento PTAX`).

| Campo da API | Coluna no Delta | Tipo PyArrow | Descrição |
|---|---|---|---|
| `dataHoraCotacao` | `data_hora_cotacao` | `timestamp[us]` | Momento exato da apuração do boletim pelo BCB |
| *derivado* | `data_referencia` | `date32` | Data normalizada do boletim |
| `cotacaoCompra` | `cotacao_compra` | `float64` | Cotação de compra em reais |
| `cotacaoVenda` | `cotacao_venda` | `float64` | Cotação de venda em reais (repassada a importados) |
| `tipoBoletim` | `tipo_boletim` | `string` | Tipo do boletim (abertura, intermediário, fechamento) |
| *partição* | `ano` | `int16` | Ano da cotação para particionamento do Delta Lake |
| Metadados | `_id_resposta`, `_fonte`, `_requisicao`, `_ingerido_em` | `string` / `timestamp` | Linhagem completa de ponta a ponta |

!!! success "Preservação da Informação Bruta (Consulta C10)"
    Ao contrário da versão anterior que descartava boletins intermediários no Python, a Bronze agora preserva todos os boletins. Isso viabiliza o cálculo analítico da volatilidade intradiária do dólar na camada Silver/Gold sem perda de dados históricos.

### 2. Taxa Selic Efetiva (SGS Série 11)

* `data/parquet/selic/resposta/`: Tabela `selic_resposta` contendo a resposta JSON bruta da API SGS.
* `data/parquet/selic/taxa_dia/`: Tabela `selic_taxa_dia` contendo a taxa apurada para cada dia útil.

| Campo da API | Coluna no Delta | Tipo PyArrow | Descrição |
|---|---|---|---|
| `data` (`DD/MM/AAAA`) | `data_referencia` | `date32` | Data do dia útil bancário |
| `valor` (string) | `taxa_dia_pct` | `float64` | Taxa Selic efetiva diária (% ao dia, ex: `0.05166`) |
| *partição* | `ano` | `int16` | Ano da taxa para particionamento |
| Metadados | `_id_resposta`, `_fonte`, `_requisicao`, `_ingerido_em` | `string` / `timestamp` | Linhagem completa |

!!! info "Sem Interpolação Prematura na Bronze"
    A Bronze registra puramente o dado publicado pelo Banco Central (apenas dias úteis). O preenchimento de fins de semana e feriados (*forward fill*) com a flag `observado = false` é uma transformação analítica e é delegado à camada Silver (E3 via dbt).

---

## Carga Histórica e Volume Medido

Executando a carga completa da janela histórica (jan/2020 a out/2026):

```bash
just bronze-macro
```

Resultados medidos no ambiente:

| Fonte | Tabela | Registros no Delta | Anos Cobertos | Volume de Arquivos |
|---|---|---|---|---|
| **Dólar** | `dolar_resposta` | 2 requisições | 2020–2026 | Partição Delta |
| **Dólar** | `dolar_boletim` | 1.703 boletins | 2020–2026 (7 anos) | Particionado por ano |
| **Selic** | `selic_resposta` | 2 requisições | 2020–2026 | Partição Delta |
| **Selic** | `selic_taxa_dia` | 1.701 taxas | 2020–2026 (7 anos) | Particionado por ano |

---

## Demonstração de Reexecução

A semântica de entrega é **efetivamente uma vez** (*exactly-once* nas tabelas):
1. A tabela de respostas calcula o SHA-256 do corpo JSON retornado. Se o hash já constar no Delta log, marca `resposta_nova = False`.
2. A gravação das tabelas de dados compara as chaves primárias contra os registros já presentes nos anos afetados e filtra duplicatas antes do append.

Execução repetida de `just bronze-macro` sobre o histórico completo:

```text
$ just bronze-macro
uv run python -m inflatrack.bronze_dolar coletar --de 2020-01-01 --ate 2026-10-13
INFO buscando dólar na API Olinda entre 01-01-2020 e 10-13-2026
INFO dolar (2020-01-01 a 2026-10-13): resposta_nova=False, lidas=1703, novas=0
uv run python -m inflatrack.bronze_selic coletar --de 2020-01-01 --ate 2026-10-13
INFO buscando série 11 no BCB/SGS
INFO selic (2020-01-01 a 2026-10-13): resposta_nova=False, lidas=1701, novas=0
```

Nenhuma linha foi duplicada e nenhuma versão redundante foi gravada no Delta Lake.

---

## Política de Dado Atrasado

* **Dólar Comercial:**
  * O Banco Central publica boletins sucessivos ao longo do dia (abertura matinal, boletins intermediários e fechamento da PTAX à tarde).
  * Se o pipeline rodar antes das 16h, os boletins parciais são capturados. Na rodada seguinte, o fechamento é incorporado naturalmente como novo registro na tabela `dolar_boletim`.
  * Em caso de reexecução, a janela relida é o ano corrente.
* **Taxa Selic Efetiva:**
  * A taxa apurada para o dia útil $T$ só é publicada pelo Banco Central no início do dia útil seguinte $T+1$ útil.
  * O pipeline trata essa defasagem estrutural: a carga de um dia útil lê com recuo de segurança (lookback), garantindo que quando o dado é publicado ele seja anexado sem deixar lacunas.

---

## Checagens de Esquema e Volume

O comando `just bronze-dolar-checar` e `just bronze-selic-checar` validam a integridade física:

```text
$ just bronze-dolar-checar
=== dolar_resposta: 2 requisições gravadas
=== dolar_boletim: 1703 boletins no histórico
  * Anos cobertos: [2020, 2021, 2022, 2023, 2024, 2025, 2026]
=== integridade da Bronze do Dólar aprovada com sucesso!

$ just bronze-selic-checar
=== selic_resposta: 2 requisições gravadas
=== selic_taxa_dia: 1701 observações no histórico
  * Anos cobertos: [2020, 2021, 2022, 2023, 2024, 2025, 2026]
=== integridade da Bronze da Selic aprovada com sucesso!
```

Validações automáticas realizadas:
* Compra e venda estritamente maiores que zero;
* Spread cambial positivo (`compra <= venda`);
* Ao menos um boletim presente por dia útil;
* Unicidade de datas na Selic;
* Taxa Selic na ordem de grandeza correta de taxa diária (`0.0 < taxa < 1.0 % ao dia`), prevenindo qualquer confusão com taxa anualizada.
