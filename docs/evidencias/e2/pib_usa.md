# Evidência E2 — PIB dos Estados Unidos (Banco Mundial)

O que a fonte `pib_usa` entrega na Entrega 2, com os comandos que produziram cada resultado. Executado contra a API pública do Banco Mundial e contra as tabelas Delta Lake locais (`deltalake` 1.6.6, `duckdb` 1.5.5, `pyarrow` 25.0.1).

!!! info "Onde está o código"
    [`src/inflatrack/bronze_pib_usa.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/bronze_pib_usa.py) (transformação em formato longo, checagens e gravação Delta), chamado por [`src/inflatrack/ingest_pib_usa.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/ingest_pib_usa.py). Testes em [`tests/test_pib_usa.py`](https://github.com/Bappoz/inflatrack/blob/main/tests/test_pib_usa.py).

## Situação das tarefas da E2

| Tarefa | Situação | Evidência |
|---|---|---|
| `pib_usa_resposta` e `pib_usa_indicador` em Delta em formato longo | Feita | [Transformação e Esquema](#transformacao-e-esquema-bronze) |
| Demonstração de reexecução e idempotência | Feita | [Demonstração de Reexecução](#demonstracao-de-reexecucao) |
| Política de dado atrasado e revisões | Feita | [Política de Dado Atrasado](#politica-de-dado-atrasado) |
| Checagens de esquema e volume | Feitas | [Checagens de Esquema e Volume](#checagens-de-esquema-e-volume) |

## Como reproduzir

```bash
# 1. Coleta direta da API e gravação em Delta
just bronze-pib-usa

# 2. Reexecução imediata para demonstrar idempotência (0 linhas novas)
just bronze-pib-usa

# 3. Verificação de integridade e contagens nas tabelas Delta
just bronze-pib-usa-checar

# 4. Execução dos testes automatizados
uv run pytest tests/test_pib_usa.py
```

## Transformação e Esquema Bronze

Na camada Bronze em Delta Lake (`data/parquet/pib_usa/`):
- `pib_usa_resposta`: Resposta JSON integral com metadados de paginação e hash SHA-256.
- `pib_usa_indicador`: Formato longo, particionado por indicador (`NY.GDP.MKTP.KD.ZG` e `NY.GDP.MKTP.CD`).

## Demonstração de Reexecução

```text
INFO coletando indicador crescimento (NY.GDP.MKTP.KD.ZG) para USA
INFO HTTP Request: GET https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.KD.ZG?format=json&per_page=1000 "HTTP/1.1 200 OK"
INFO NY.GDP.MKTP.KD.ZG: resposta_nova=False, lidas=66, novas=0
INFO coletando indicador pib_usd (NY.GDP.MKTP.CD) para USA
INFO HTTP Request: GET https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.CD?format=json&per_page=1000 "HTTP/1.1 200 OK"
INFO NY.GDP.MKTP.CD: resposta_nova=False, lidas=66, novas=0
```

Resultado verificado por `just bronze-pib-usa-checar`:
- `pib_usa_resposta`: 2 linhas
- `pib_usa_indicador`: 132 linhas (66 anos de histórico contínuo desde 1960).

## Política de Dado Atrasado

Série histórica anual consolidada pelo BEA/Banco Mundial. Revisões anuais alteram o hash SHA-256 gerando novas versões da resposta e novas linhas na tabela Delta de indicadores preservando histórico.

## Checagens de Esquema e Volume

O módulo `bronze_pib_usa.checar` valida antes de gravar:
- Ausência de duplicidade para o par `(indicador, ano)`;
- Cobertura temporal contínua com início em 1960;
- Volume esperado de $\ge 55$ anos históricos por série.
