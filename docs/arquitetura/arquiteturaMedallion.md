# Arquitetura Medallion

O Medallion é a arquitetura **alvo** do pipeline analítico do InflaTrack. A
implementação está em transição: Raw e partes da Bronze já existem, enquanto
Silver e Gold comuns ainda dependem da criação do projeto dbt. Alguns
carregadores legados também levam Parquet diretamente ao DuckDB. Portanto, não
se deve entender o diagrama como se todas as fontes já percorressem as quatro
camadas.

O PostgreSQL roda em paralelo e guarda o lado transacional — cadastro e
histórico de reajustes — além da referência atual do IPCA/INPC. Ele não é uma
camada do Medallion.

## As quatro camadas

| Camada | Tecnologia | Papel | Estado no repositório |
|---|---|---|---|
| **Raw** | Respostas JSON/HTML comprimidas com gzip em `data/raw/<fonte>/` | Preservar a entrada para auditoria e reprocessamento. | Em uso; cargas históricas importadas podem conter respostas reserializadas pelo fluxo antigo. |
| **Bronze** | Tabelas Delta Lake sobre Parquet em `data/parquet/<fonte>/`; há também Parquet simples nos fluxos legados. | Guardar payload tipado por fonte, ainda sem regra analítica comum. | Parcialmente migrada; fontes e comandos indicam qual formato usam. |
| **Silver** | Modelos SQL em `dbt-duckdb` | Limpar, deduplicar e conformar cada fonte. | Planejada; dbt e `models/` ainda não estão no projeto. |
| **Gold** | Tabelas analíticas no DuckDB produzidas a partir de `models/marts/` | Cruzar as fontes e fornecer métricas para painel e análise. | Planejada como camada comum. Já existem tabelas e views DuckDB específicas por fonte, mas não a Gold dimensional descrita aqui. |

<div class="diagrama">
--8<-- "docs/assets/diagramas/medallion.svg"
</div>

## Bronze atual por fonte

O diretório `data/parquet/` é o nome histórico compartilhado. Nas fontes
migradas, as subpastas contêm tabelas Delta (arquivos Parquet e log
`_delta_log`); não são necessariamente arquivos `.parquet` independentes.

| Fonte | Raw | Bronze implementada |
|---|---|---|
| [IPCA/INPC (SIDRA)](../fontes/sidra.md) | `data/raw/ipca-inpc/` | Delta em `data/parquet/ipca/` (`ipca_resposta`, `ipca_observacao`) |
| [Commodities e Energia](../fontes/commodities.md) | `data/raw/commodities_raw/` | Parquet simples em `data/parquet/`; o glob legado espera o esquema de commodities |
| [Dólar Comercial](../fontes/dolar.md) | `data/raw/bcb/` | Delta em `data/parquet/dolar/`; há também carga legada direta ao DuckDB |
| [Taxa SELIC](../fontes/selic.md) | `data/raw/bcb/` | Delta em `data/parquet/selic/`; há também carga legada direta ao DuckDB |
| [PIB e Setores (SIDRA 1846)](../fontes/pib.md) | `data/raw/pib_raw/` | Parquet simples em `data/parquet/pib/`, carregado diretamente no DuckDB |
| [PIB da China](../fontes/pib_china.md) | `data/raw/pib_china/` | Delta em `data/parquet/pib_china/`; o fluxo legado também grava Parquet simples |
| [PIB dos EUA](../fontes/pib_usa.md) | `data/raw/pib_usa/` | Delta em `data/parquet/pib_usa/` |
| [PIB da Rússia](../fontes/pib_russia.md) | `data/raw/pib_russia/` | Delta em `data/parquet/pib_russia/` |
| [Salário Mínimo (DIEESE)](../fontes/salario_minimo.md) | `data/raw/dieese/` | Delta em `data/parquet/salario_minimo/`; o fluxo legado usou `data/parquet/dieese/` |
| [Dados do Clima (INMET)](../fontes/clima.md) | `data/raw/inmet/` | Delta em `data/parquet/clima/` |

## Fluxo alvo

**Origem → Raw.** A resposta é guardada comprimida antes de ser interpretada,
para que uma transformação possa ser refeita sem consultar a API. O histórico
importado pode ter limitações: por exemplo, parte dos arquivos antigos do SIDRA
foi reserializada pelo ingestor anterior, conforme a [evidência da E2](../evidencias/e2/ipca.md#importacao-do-raw-antigo).

**Raw → Bronze.** O ingestor interpreta o formato de cada origem, tipa os
campos e registra procedência. Na E2, Delta Lake adiciona log de versões e
escritas idempotentes sobre os arquivos Parquet. Algumas fontes ainda usam o
caminho legado de Parquet simples.

**Bronze → Silver (planejado).** O dbt deverá tratar marcadores de ausência,
deduplicar revisões e alinhar chaves. O preenchimento de dias sem publicação do
BCB é uma proposta do [ADR 0003](../adr/0003-bcb-macro.md), não um comportamento
atual.

**Silver → Gold (planejado).** Os modelos deverão cruzar as fontes em fatos,
dimensões e métricas com granularidade declarada, preparando as tabelas para o
painel e para experimentos. Os loaders atuais criam estruturas específicas por
fonte e ainda não equivalem a esse modelo dimensional comum.

## Qualidade e limites atuais

- Existem checagens específicas por fonte, como esquema, volume, meses ausentes
  e idempotência; os comandos `just bronze-*-checar` documentam as que estão
  implementadas.
- Testes e linhagem de dbt, freshness checks e matriz Gold permanecem
  planejados; não são controles que a pipeline atual já execute.
- O Dagster orquestra ingestões e mantém histórico de execução. A integração
  `dagster-dbt` depende da criação dos modelos dbt.
- A camada IPCA no PostgreSQL preserva valores revisados, mas ainda substitui
  nomes de categorias quando recebe uma renomeação. A dimensão histórica está
  pendente no [ADR 0001](../arquitetura.md).
