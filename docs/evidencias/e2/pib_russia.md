# Evidência E2 — PIB da Rússia (Banco Mundial)

O que a fonte `pib_russia` entrega na Entrega 2, com os comandos que produziram cada resultado. Executado contra a API pública do Banco Mundial e contra as tabelas Delta Lake locais (`deltalake` 1.6.6, `duckdb` 1.5.5, `pyarrow` 25.0.1).

!!! info "Onde está o código"
    [`src/inflatrack/bronze_pib_russia.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/bronze_pib_russia.py) (transformação em formato longo, checagens e gravação Delta), chamado por [`src/inflatrack/ingest_pib_russia.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/ingest_pib_russia.py). Testes em [`tests/test_pib_russia.py`](https://github.com/Bappoz/inflatrack/blob/main/tests/test_pib_russia.py).

## Situação das tarefas da E2

| Tarefa | Situação | Evidência |
|---|---|---|
| `pib_russia_resposta` e `pib_russia_indicador` em Delta em formato longo | Feita | [Transformação e Esquema](#transformacao-e-esquema-bronze) |
| Preservação de nulos históricos (período soviético 1960–1989) | Feita | [Tratamento dos Nulos Soviéticos](#tratamento-dos-nulos-sovieticos) |
| Demonstração de reexecução e idempotência | Feita | [Demonstração de Reexecução](#demonstracao-de-reexecucao) |
| Política de dado atrasado e revisões | Feita | [Política de Dado Atrasado](#politica-de-dado-atrasado) |
| Checagens de esquema e volume | Feitas | [Checagens de Esquema e Volume](#checagens-de-esquema-e-volume) |

## Como reproduzir

```bash
# 1. Coleta direta da API e gravação em Delta
just bronze-pib-russia

# 2. Reexecução imediata para demonstrar idempotência (0 linhas novas)
just bronze-pib-russia

# 3. Verificação de integridade e contagens nas tabelas Delta
just bronze-pib-russia-checar

# 4. Execução dos testes automatizados
uv run pytest tests/test_pib_russia.py
```

## Transformação e Esquema Bronze

Na camada Bronze em Delta Lake (`data/parquet/pib_russia/`):
- `pib_russia_resposta`: Resposta JSON integral com metadados de paginação e hash SHA-256.
- `pib_russia_indicador`: Formato longo, particionado por indicador (`NY.GDP.MKTP.KD.ZG` e `NY.GDP.MKTP.CD`).

## Tratamento dos Nulos Soviéticos

A grade da API do Banco Mundial devolve 66 anos (1960 a 2025). Como a Federação Russa surge no fim de 1989/1990, os anos de 1960 a 1989 chegam com `value: null`. A camada Bronze preserva fielmente todos os 66 anos no Parquet e Delta Lake, garantindo integridade e conformidade de linhagem sem descartar registros antecipadamente.

## Demonstração de Reexecução

```text
INFO coletando indicador crescimento (NY.GDP.MKTP.KD.ZG) para RUS
INFO HTTP Request: GET https://api.worldbank.org/v2/country/RUS/indicator/NY.GDP.MKTP.KD.ZG?format=json&per_page=1000 "HTTP/1.1 200 OK"
INFO NY.GDP.MKTP.KD.ZG: resposta_nova=False, lidas=66, novas=0
INFO coletando indicador pib_usd (NY.GDP.MKTP.CD) para RUS
INFO HTTP Request: GET https://api.worldbank.org/v2/country/RUS/indicator/NY.GDP.MKTP.CD?format=json&per_page=1000 "HTTP/1.1 200 OK"
INFO NY.GDP.MKTP.CD: resposta_nova=False, lidas=66, novas=0
```

## Política de Dado Atrasado

Série histórica anual consolidada pelo Rosstat/Banco Mundial. Revisões anuais alteram o hash SHA-256 gerando novas versões da resposta e novas linhas na tabela Delta de indicadores preservando histórico.

## Checagens de Esquema e Volume

O módulo `bronze_pib_russia.checar` valida antes de gravar:
- Ausência de duplicidade para o par `(indicador, ano)`;
- Grade temporal de 66 anos (1960 a 2025);
- Preservação de nulos históricos legítimos no período soviético (1960–1989);
- Presença de pelo menos 30 anos com valores válidos a partir de 1990.
