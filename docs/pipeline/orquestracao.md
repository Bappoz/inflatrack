# Orquestração (Dagster)

O **Dagster** é o orquestrador do InflaTrack: é ele que decide *quando* cada pedaço do dado é produzido, *em que ordem* e *o que refazer* quando algo falha. Ele substitui o disparo manual das receitas do `justfile` sem mudar o código de ingestão — as receitas continuam existindo como caminho manual de emergência.

!!! info "Status: em uso nos ingestores"
    O código está em `orchestration/` e cobre as etapas E1, E2 e E7 (Raw, Bronze e a referência do IPCA no Postgres). Os assets dbt (E3/E4) e o de publicação (E6) entram quando o projeto dbt existir. A divisão de responsabilidades sustenta o [ADR 0002](../adr/0002-duckdb-unico.md) e os [Componentes](../arquitetura/componentes.md#dagster).

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

| Grupo | Ativos | Destino | Módulo chamado |
|---|---|---|---|
| `sidra` | `ipca`, `inpc`, `ipca_numero_indice` | PostgreSQL | `ingest` (o agregado é escolhido pelo mês da partição: 2938, 1419 ou 7060) |
| `macro` | `dolar`, `selic` | DuckDB | `ingest_dolar`, `ingest_selic` |
| `commodities` | `commodities_parquet` → `commodities_duckdb` | Parquet → DuckDB | `ingest_commodities`, `load_commodities` |
| `pib` | `pib_parquet` → `pib_duckdb` | Parquet → DuckDB | `ingest_pib`, `load_pib` |
| `pib_china` | `pib_china_parquet` → `pib_china_duckdb` | Parquet → DuckDB | `ingest_pib_china`, `load_pib_china` |
| `dieese` | `salario_minimo_parquet` → `salario_minimo_duckdb` | Parquet → DuckDB | `ingest_salario_minimo`, `load_salario_minimo` |
| `clima` | `clima_parquet` → `clima_duckdb` | Parquet → DuckDB | `ingest_clima`, `load_clima` |

## Organização do código

```
orchestration/
├── definitions.py          # Definitions: assets, jobs e schedules
├── assets/
│   ├── ingestao.py         # um asset por etapa, chamando src/inflatrack/ingest_*.py e load_*.py
│   ├── dbt.py              # (planejado) @dbt_assets — carrega o manifest do projeto dbt
│   └── publicacao.py       # (planejado) cópia da Gold lida pelo Streamlit
├── partitions.py           # partições mensais do IPCA/INPC e a vigência de cada agregado
└── schedules.py            # um job e um agendamento por grupo de ativos
.dagster/dagster.yaml       # instância local: pool duckdb_writer com limite 1
```

A lógica de negócio **não muda de lugar**: cada asset chama o mesmo `main(argv)` que a receita do `justfile` chama e transforma código de saída ≠ 0 em falha. O Dagster fica com a orquestração, e nada mais — o mesmo princípio que mantém o cliente de origem ignorante sobre disco e banco.

Só o IPCA/INPC é particionado. As demais fontes já baixam a janela inteira e fazem *upsert*; particioná-las por dia multiplicaria chamadas de API sem ganho, porque o reprocesso já é idempotente.

## Partições e agendamento

| Grupo de ativos | Partição | Agendamento previsto | Origem da cadência |
|---|---|---|---|
| IPCA/INPC (SIDRA) | Mensal | Dias 9 a 13, 1×/dia até materializar | Divulgação do IBGE |
| PIB e setores (SIDRA 1846) | Trimestral | Diário no mês de divulgação | Contas nacionais trimestrais |
| Dólar e Selic (BCB) | Diária | Dias úteis, após o fechamento | Publicação do BCB |
| Commodities (Alpha Vantage) | Diária | 1×/dia, respeitando a cota de 25 req./dia | Cota da API |
| Clima (INMET) | Diária | 1×/dia | Estações automáticas |
| Salário mínimo (DIEESE) | Mensal | 1×/mês | Publicação do DIEESE |
| PIB da China (Banco Mundial) | Anual | 1×/mês (detecta revisão) | Revisões fora de calendário |
| Silver e Gold (dbt) | Herdada da fonte | Disparado pelo *upstream* | Dependência do grafo |

Fontes com calendário irregular (o IBGE às vezes antecipa, o DIEESE não tem dia fixo) usam agendamento **tolerante**: roda todo dia da janela e o asset só materializa quando o dado novo aparece — mais barato que acertar a data exata.

## Confiabilidade

* **Retry por asset** — até 2 novas tentativas com backoff exponencial, esperando 30 s e depois 90 s. A exceção são as commodities: sem retry, porque cada tentativa gasta 9 das 25 requisições diárias da Alpha Vantage.
* **Concorrência** — pool `duckdb_writer` com limite 1 (`.dagster/dagster.yaml`): qualquer asset que escreva no arquivo entra na fila.
* **Idempotência** — garantida pelo próprio código de ingestão (`ON CONFLICT DO UPDATE` e Raw imutável), não pelo orquestrador. Rodar duas vezes a mesma partição não duplica linha.
* **Testes de qualidade** — ficam nos `dbt tests`, dentro da transformação; o Dagster apenas propaga a falha e interrompe o *downstream*.

## Execução local

```bash
just orquestrador           # interface em http://localhost:3000, histórico em .dagster/
just materializar macro_job # roda um job sem abrir a interface
```

A partir da interface: materializar um ativo, selecionar um intervalo de partições para backfill (um intervalo do IPCA vira uma única execução, quebrada por agregado), ou inspecionar a última execução de cada ativo.

!!! warning "Agendamentos nascem desligados"
    Ligue cada um em *Automation* na interface. Assim, abrir o `dagster dev` não chama nenhuma API nem gasta a cota da Alpha Vantage. Os ativos do grupo `sidra` precisam do Postgres no ar (`just up`).

Os agendamentos seguem a tabela acima. Os do SIDRA rodam nos dias 9 a 13: pedem a partição do mês anterior enquanto ela não estiver materializada e, uma vez por ciclo, releem os três meses antes dela, para captar revisão do IBGE (ver [política de dado atrasado do IPCA](../evidencias/e2/ipca.md#politica-de-dado-atrasado)).

Enquanto o IBGE não divulga o mês, o SIDRA responde com uma lista vazia e a execução do dia **falha de propósito** (`sem dados publicados`), sem gravar nada no Raw. Uma execução vermelha nesses dias é esperada: ela mantém a partição pendente para o agendamento tentar de novo no dia seguinte. Se o mês fosse marcado como carregado, os dias seguintes seriam pulados e o mês nunca entraria.

## O que falta

1. Criar o projeto dbt (`models/staging/` e `models/marts/`) e adicionar `dagster-dbt` — pré-requisito dos assets das etapas E3 e E4.
2. Asset de publicação da Gold para o Streamlit (E6).
3. *Freshness checks* por ativo, com o SLA de cada fonte.
4. Erros de esquema ainda são repetidos pelo retry: os módulos de ingestão não distinguem erro de rede de erro de payload no código de saída.
