# Evidência E2 — PIB da China (Banco Mundial)

O que a fonte `pib_china` entrega na Entrega 2, com os comandos que produziram cada resultado. Tudo nesta página foi executado contra a API pública do Banco Mundial e contra as tabelas Delta Lake locais (`deltalake` 1.6.6, `duckdb` 1.5.5, `pyarrow` 25.0.1).

!!! info "Onde está o código"
    [`src/inflatrack/bronze_pib_china.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/bronze_pib_china.py) (transformação em formato longo, checagens, gravação Delta e importação do raw), chamado por [`src/inflatrack/ingest_pib_china.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/ingest_pib_china.py). Testes em [`tests/test_pib_china.py`](https://github.com/Bappoz/inflatrack/blob/main/tests/test_pib_china.py).

## Situação das tarefas da E2

Itens da seção 3.6 do [plano de trabalho](../../tasks_entrega_2.md#36-pib-da-china-banco-mundial).

| Tarefa | Situação | Evidência |
|---|---|---|
| `pib_china_resposta` e `pib_china_indicador` em Delta em formato longo | Feita | [Transformação e Esquema](#transformacao-e-esquema-bronze) |
| Importar o Raw existente para `pib_china_resposta` | Feita | [Importação do Raw](#importacao-do-raw-antigo) |
| Demonstração de reexecução e idempotência | Feita | [Demonstração de Reexecução](#demonstracao-de-reexecucao) |
| Política de dado atrasado e revisões | Feita | [Política de Dado Atrasado](#politica-de-dado-atrasado) |
| Checagens de esquema e volume | Feitas | [Checagens de Esquema e Volume](#checagens-de-esquema-e-volume) |
| Diário de bordo das Semanas 7 a 10 | Pendente | Registro individual |

## Como reproduzir

```bash
# 1. Coleta direta da API e gravação em Delta (resposta + indicador)
just bronze-pib-china

# 2. Reexecução imediata para demonstrar idempotência (0 linhas novas)
just bronze-pib-china

# 3. Verificação de integridade e contagens nas tabelas Delta
just bronze-pib-china-checar

# 4. Importação dos arquivos .json.gz antigos (se existirem)
just bronze-pib-china-importar

# 5. Execução dos testes automatizados (unitários e de idempotência)
uv run pytest tests/test_pib_china.py
```

## Transformação e Esquema Bronze

Na camada Bronze em Delta Lake, o PIB da China mantém **duas tabelas** em `data/parquet/pib_china/`:

1. **`pib_china_resposta`**: Armazena o JSON completo retornado pela API, inclusive metadados de paginação (`page`, `pages`, `per_page`, `total`), status HTTP e hash SHA-256 do corpo.
2. **`pib_china_indicador`**: Tabela extraída em **formato longo**, preservando todos os atributos da API sem perdas nem agregações antecipadas.

| Campo da API | Coluna no Delta | Tipo | Descrição |
|---|---|---|---|
| `indicator.id` | `indicador` | String (Partição) | Código do indicador (`NY.GDP.MKTP.KD.ZG` ou `NY.GDP.MKTP.CD`) |
| `date` | `ano` | Int16 | Ano civil (1960–2025) |
| `value` | `valor` | Float64 | Valor da observação (anulável para o ano mais recente) |
| `indicator.value` | `indicador_nome` | String | Nome descritivo do indicador |
| `country.id` | `pais_id` | String | Código do país (`CN`) |
| `country.value` | `pais_nome` | String | Nome do país (`China`) |
| `countryiso3code` | `pais_iso3` | String | Código ISO3 (`CHN`) |
| `unit` | `unidade` | String | Unidade informada |
| `obs_status` | `obs_status` | String | Status de observação |
| `decimal` | `decimal` | Int16 | Precisão decimal |
| Metadados de Linhagem | `_id_resposta`, `_fonte`, `_requisicao`, `_ingerido_em` | String / Timestamp | Linhagem de ponta a ponta até a chamada |

## Carga Histórica e Importação do Raw

A importação dos arquivos `.json.gz` existentes em `data/raw/pib_china/` migrou todo o histórico para as tabelas Delta:

```text
INFO importando raw NY.GDP.MKTP.CD.json.gz -> indicador NY.GDP.MKTP.CD
INFO importado NY.GDP.MKTP.CD.json.gz: resposta_nova=True, observacoes_novas=66
INFO importando raw NY.GDP.MKTP.KD.ZG.json.gz -> indicador NY.GDP.MKTP.KD.ZG
INFO importado NY.GDP.MKTP.KD.ZG.json.gz: resposta_nova=True, observacoes_novas=66
```

Totalizando 132 observações (66 anos de histórico para cada série).

## Demonstração de Reexecução

A reexecução da coleta pela API é estritamente idempotente. As requisições são verificadas contra o hash SHA-256 já existente na tabela `pib_china_resposta`.

Execução consecutiva do comando `just bronze-pib-china`:

```text
--- Execução 1 (captura inicial / atualização):
INFO coletando indicador crescimento (NY.GDP.MKTP.KD.ZG)
INFO HTTP Request: GET https://api.worldbank.org/v2/country/CHN/indicator/NY.GDP.MKTP.KD.ZG?format=json&per_page=1000 "HTTP/1.1 200 OK"
INFO NY.GDP.MKTP.KD.ZG: resposta_nova=False, lidas=66, novas=0
INFO coletando indicador pib_usd (NY.GDP.MKTP.CD)
INFO HTTP Request: GET https://api.worldbank.org/v2/country/CHN/indicator/NY.GDP.MKTP.CD?format=json&per_page=1000 "HTTP/1.1 200 OK"
INFO NY.GDP.MKTP.CD: resposta_nova=False, lidas=66, novas=0

--- Verificação de Estado (just bronze-pib-china-checar):
=== pib_china_resposta: 6 linhas (registros imutáveis de requisições)
=== pib_china_indicador: 132 linhas
  * Indicador NY.GDP.MKTP.CD: 66 linhas, 66 anos distintos, 0 nulos
  * Indicador NY.GDP.MKTP.KD.ZG: 66 linhas, 66 anos distintos, 1 nulos
```

Nenhuma linha nova foi duplicada na tabela de indicadores.

## Checagens de Esquema e Volume

O módulo `bronze_pib_china.checar` valida antes de gravar:
- Ausência de duplicidade para o par `(indicador, ano)`;
- Cobertura temporal contínua com início $\le 1965$;
- Volume esperado de $\ge 55$ anos históricos por série;
- Suporte a valor nulo no ano civil corrente/recente (característica documentada da API do Banco Mundial).

## Política de Dado Atrasado

- **Revisão fora de calendário:** O Banco Mundial revisa a série histórica periodicamente.
- **Detecção de revisão:** Como a requisição traz a série inteira em cada chamada, qualquer alteração no histórico altera o SHA-256 do corpo, gerando uma nova versão na tabela `pib_china_resposta`. Na tabela `pib_china_indicador`, como a chave de deduplicação inclui o valor (`indicador, ano, valor`), qualquer ano que sofra alteração de valor entra como um novo registro com o timestamp `_ingerido_em` da revisão, permitindo rastrear revisões na Prata/dbt sem perda do dado anterior.
