# Orquestração (Dagster)

O **Dagster** é o orquestrador do InflaTrack: é ele que decide *quando* cada pedaço do dado é produzido, *em que ordem* e *o que refazer* quando algo falha. Ele substitui o disparo manual das receitas do `justfile` sem mudar o código de ingestão — as receitas continuam existindo como caminho manual de emergência.

!!! info "Status: em uso de ponta a ponta (E3)"
    O código está em `orchestration/` e cobre a Bronze de todas as fontes, a Silver e a Gold do dbt (`dbt_assets.py`), a cópia da Gold para o `serie` do Postgres (`serie.py`) e os *asset checks* de frescura (`checks.py`). Falta o ETL reverso da recomendação ao lojista (E4). A divisão de responsabilidades sustenta o [ADR 0002](../adr/0002-duckdb-unico.md) e os [Componentes](../arquitetura/componentes.md#dagster).

## Por que Dagster e não Airflow

| Critério | Airflow | Dagster | Escolha |
|---|---|---|---|
| Unidade de orquestração | Tarefa (o que executar) | **Ativo de dado** (o que deve existir) | Dagster — nosso pipeline é definido pelas tabelas que precisam estar atualizadas |
| Integração com dbt | Via Cosmos, camada extra | `dagster-dbt` nativo: cada model vira um asset | Dagster |
| Backfill histórico | DAG run por data | Partição por asset, com estado por partição | Dagster — o IPCA é mensal e tem 20 anos de histórico |
| Frescor do dado | Fora do núcleo | *Freshness* é conceito de primeira classe | Dagster |
| Tarefas operacionais (e-mail, rotina em servidor) | Forte | Possível, não é o foco | Airflow venceria — não é o nosso caso |

O Airflow é excelente para **tarefas**; o InflaTrack orquestra **dados**. Nenhuma etapa nossa é "mandar um e-mail" ou "rodar um script no servidor": toda etapa produz uma tabela ou um arquivo que alguém consulta depois.

## O que o Dagster faz aqui

* **Executa o grafo inteiro** — ingestores Python e `dbt build` no mesmo grafo de dependência, sem um `just` manual por fonte.
* **Repete só o que falhou** — retry por asset; se o INMET cair, o IPCA não é reprocessado.
* **Roda backfill por partição** — recarregar jan/2020 a dez/2021 do IPCA é selecionar um intervalo de partições, não editar um comando.
* **Serializa o escritor do DuckDB** — um limite de concorrência global garante o escritor único que o arquivo exige.
* **Expõe o estado do dado** — a interface mostra, por ativo, quando foi materializado pela última vez e se está fora do prazo de frescor.

## O grafo de ativos

<div class="diagrama">
--8<-- "docs/assets/diagramas/orquestracao-assets.svg"
</div>

Cada caixa é um **ativo**: uma coisa que precisa existir e estar atualizada. O Dagster não pergunta "essa tarefa rodou?", e sim "esse dado está lá e está fresco?".

### Ativos implementados hoje

Todo ativo que abre o DuckDB entra no pool `duckdb_writer` (um escritor por vez).

| Grupo | Ativos | Destino | Módulo chamado |
|---|---|---|---|
| `sidra` | `ipca`, `inpc`, `ipca_numero_indice` → `ipca_duckdb` + `ipca_metadados_duckdb` | Delta (+ Postgres) → DuckDB | `bronze.ipca`, `loaders.load_ipca` |
| `macro` | `dolar_parquet` → `dolar_duckdb`, `selic_parquet` → `selic_duckdb` | Delta → DuckDB | `bronze.dolar`, `bronze.selic`, `loaders.load_dolar`, `loaders.load_selic` |
| `commodities` | `commodities_parquet` → `commodities_duckdb` | Delta → DuckDB | `bronze.commodities`, `loaders.load_commodities` |
| `pib` | `pib_parquet` → `pib_duckdb` (a carga roda no `analitico_job`, como a do IPCA) | Delta → DuckDB | `bronze.pib`, `loaders.load_pib` |
| `pib_internacional` | `pib_china_parquet`, `pib_usa_parquet`, `pib_russia_parquet` → `pib_internacional_duckdb` | Delta → DuckDB | `bronze.pib_internacional`, `loaders.load_pib_internacional` |
| `dieese` | `salario_minimo_parquet` → `salario_minimo_duckdb` | Delta → DuckDB | `ingest_salario_minimo`, `load_salario_minimo` |
| `clima` | `clima_parquet` → `clima_duckdb` | Delta → DuckDB | `ingest_clima`, `load_clima` |
| `clima_medicoes` | `clima_medicoes` → `clima_medicoes_duckdb` | Delta → DuckDB | `ingest_clima`, `load_clima` |
| `transacional` | `transacional_delta` → `transacional_duckdb` | Delta → DuckDB | `cdc.transacional`, `loaders.load_transacional` |
| `silver`, `gold` | modelos do dbt | DuckDB | `dbt build` (`dbt_assets.py`) |
| `vitrine` | `serie_postgres` | Postgres (`serie`) | `reverse_etl.exportar_serie` |

## Organização do código

```
orchestration/
├── definitions.py          # Definitions: carrega todo módulo de assets/, jobs e schedules
├── assets/
│   ├── comum.py            # pool duckdb_writer, retry de rede e a chamada do main(argv)
│   ├── pib.py              # um módulo por fonte (modelo para as outras)
│   ├── commodities.py, dolar.py, selic.py, salario_minimo.py, clima.py, pib_internacional.py
│   ├── ipca.py             # IPCA, INPC e número-índice, particionados por mês, e a carga no DuckDB
│   ├── transacional.py     # CDC do banco do lojista e a carga no DuckDB
│   ├── dbt_assets.py       # @dbt_assets: Silver e Gold, ligados às cargas pelo meta.dagster.asset_key
│   ├── serie.py            # serie_postgres: cópia da Gold para o schema serie (Metabase)
│   └── checks.py           # asset checks de frescura e volume
├── partitions.py           # partições mensais do IPCA/INPC e a vigência de cada agregado
├── schedules.py            # um job e um agendamento por grupo de ativos
└── popular.py              # popular_banco_job: dispara todos os jobs de fonte numa máquina nova
.dagster/dagster.yaml       # instância local: pool duckdb_writer com limite 1
```

A lógica de negócio **não muda de lugar**: cada asset chama o mesmo `main(argv)` que a receita do `justfile` chama e transforma código de saída ≠ 0 em falha. A exceção são as coletas particionadas (IPCA, INPC, número-índice e PIB): elas chamam a função de coleta que o `main` usa, porque precisam saber quais períodos vieram. Período ainda não divulgado (o mês corrente, o ano sem trimestre) é pulado e a partição dele fica *pendente*, não materializada; um backfill até o mês corrente traz o resto sem falhar. Se nada do intervalo saiu, o passo falha sem retry. O Dagster fica com a orquestração, e nada mais — o mesmo princípio que mantém o cliente de origem ignorante sobre disco e banco.

Só o IPCA/INPC (por mês) e o PIB (por ano) são particionados. As demais fontes já baixam a janela inteira e fazem *upsert*; particioná-las por dia multiplicaria chamadas de API sem ganho, porque o reprocesso já é idempotente.

## Partições e agendamento

| Grupo de ativos | Partição | Agendamento previsto | Origem da cadência |
|---|---|---|---|
| IPCA/INPC (SIDRA) | Mensal | Dias 9 a 13, 1×/dia até materializar | Divulgação do IBGE |
| PIB e setores (SIDRA 1846) | Anual (relê o ano corrente e o anterior) | Diário nos meses de divulgação (mar, jun, set, dez) | Contas nacionais trimestrais |
| Dólar e Selic (BCB) | Diária | Dias úteis, após o fechamento | Publicação do BCB |
| Commodities (Alpha Vantage) | Diária | 1×/dia, respeitando a cota de 25 req./dia | Cota da API |
| Clima (INMET) | — | Catálogo 1×/dia; medições só manuais (`clima_medicoes`) | Estações automáticas |
| Salário mínimo (DIEESE) | Mensal | 1×/mês | Publicação do DIEESE |
| PIB internacional (Banco Mundial) | — | 1×/mês, dia 1 (detecta revisão) | Revisões fora de calendário |
| Silver, Gold e vitrine (`analitico_job`) | — | 1×/dia às 20h30, depois das fontes | Dependência do grafo |

Fontes com calendário irregular (o IBGE às vezes antecipa, o DIEESE não tem dia fixo) usam agendamento **tolerante**: roda todo dia da janela e o asset só materializa quando o dado novo aparece — mais barato que acertar a data exata.

## Confiabilidade

* **Retry por asset** — até 2 novas tentativas com backoff exponencial, esperando 30 s e depois 90 s. A exceção são as commodities: sem retry, porque cada tentativa gasta 9 das 25 requisições diárias da Alpha Vantage.
* **Concorrência** — pool `duckdb_writer` com limite 1 (`.dagster/dagster.yaml`): qualquer asset que escreva no arquivo entra na fila.
* **Idempotência** — garantida pelo próprio código de ingestão (`ON CONFLICT DO UPDATE` e Raw imutável), não pelo orquestrador. Rodar duas vezes a mesma partição não duplica linha.
* **Testes de qualidade** — ficam nos `dbt tests`, dentro da transformação; o Dagster apenas propaga a falha e interrompe o *downstream*.

## Execução local

```bash
just orquestrador           # interface em http://localhost:3002 (DAGSTER_PORT), histórico em .dagster/
just materializar macro_job # roda um job sem abrir a interface
```

A partir da interface: materializar um ativo, selecionar um intervalo de partições para backfill (um intervalo do IPCA vira uma única execução, quebrada por agregado), ou inspecionar a última execução de cada ativo.

!!! warning "Agendamentos nascem desligados"
    Ligue cada um em *Automation* na interface. Assim, abrir o `dagster dev` não chama nenhuma API nem gasta a cota da Alpha Vantage. Os ativos do grupo `sidra` precisam do Postgres no ar (`just up`).

### Primeira execução numa máquina nova

`popular_banco_job` (em `orchestration/popular.py`) enche a Bronze do zero. Ele não é um job de ativos: IPCA, INPC e número-índice são particionados por mês e o PIB por ano, e o Dagster recusa partições diferentes num mesmo job de ativos. Em vez disso, cada op pede ao webserver (API GraphQL, porta `DAGSTER_PORT`) que dispare um job de fonte como run separado e espera o fim. Os particionados vão com o intervalo completo (IPCA desde 2006, número-índice desde 1979, INPC desde 2020, PIB desde 1996), que vira um run só por causa do `BackfillPolicy.single_run()`.

Os jobs rodam em paralelo, com uma exceção: o `transacional_job` espera as três coletas do SIDRA. A carga completa do IPCA grava ~6 milhões de linhas em `public.observacao` (mais de 2 GB de WAL); com o slot do CDC criado no meio dela e sem leitura, o Postgres o invalida por `max_slot_wal_keep_size` (visto num clone limpo em 2026-11-08). O banco do lojista nasce vazio: para a P5 ter dado, rode `just simular-cdc` antes do `analitico_job`.

Uma fonte que falha deixa o run dela vermelho e **não impede as outras**: a op `resumo` lista quem falhou e marca só então o job pai como falho. Lançar de novo refaz apenas o que falta, porque os coletores pulam o que já existe. Silver, Gold e vitrine ficam de fora de propósito: depois rode o `analitico_job`.

Exige o `dagster dev` no ar (é lançado pela interface, não por `just materializar`), o Postgres (`just up`) para o grupo `sidra`, e a chave da Alpha Vantage para commodities. O IPCA completo leva cerca de 20 minutos; as medições de clima não entram (o ativo `clima_medicoes` é manual).

Os agendamentos seguem a tabela acima. Os do SIDRA rodam nos dias 9 a 13: pedem a partição do mês anterior enquanto ela não estiver materializada e, uma vez por ciclo, releem os três meses antes dela, para captar revisão do IBGE (ver [política de dado atrasado do IPCA](../evidencias/e2/ipca.md#politica-de-dado-atrasado)).

Enquanto o IBGE não divulga o mês, o SIDRA responde com uma lista vazia. O mês é pulado sem gravar nada e a partição dele fica *pendente* (não materializada), então o agendamento pede de novo no dia seguinte; os outros meses do intervalo são materializados normalmente. A execução só fica vermelha quando **nenhum** mês do intervalo saiu (`nada de ... foi divulgado pela fonte ainda`), e sem retry, porque esperar 30 s não faz o IBGE publicar. Se o mês fosse marcado como carregado sem dado, os dias seguintes seriam pulados e o mês nunca entraria.

## O que falta

1. *Freshness checks* das outras fontes: hoje só Dólar, Selic e `gold.fct_macroeconomia_mensal` têm SLA declarado e checado (`checks.py`, ver [evidência](../evidencias/e3/sla_e_freshness.md)).
2. Medições do clima no agendamento: `clima_medicoes` exige estações e intervalo por config e fica fora do `clima_job` e do `popular_banco_job`.
3. ETL reverso da recomendação de reajuste para o banco do lojista (E4).
4. Erros de esquema ainda são repetidos pelo retry: fora do "nada divulgado ainda" das coletas particionadas (que falha sem retry), os módulos de ingestão não distinguem erro de rede de erro de payload no código de saída.
