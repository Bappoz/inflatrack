# Contrato das Etapas

Cada etapa do pipeline respondida na mesma grade: de onde vem, para onde vai, o que é feito no caminho, quando roda, quanto custa atrasar e como a Squad descobre que quebrou.

São sete etapas. Elas estão desenhadas em [Fluxo de Dados](../arquitetura/fluxoDados.md) e executadas pelo [Dagster](orquestracao.md).

| # | Etapa | Status |
|---|---|---|
| **E1** | Extração e aterrissagem (Raw) | Em uso |
| **E2** | Materialização Bronze (Parquet) | Em uso |
| **E3** | Silver (dbt) | Planejado |
| **E4** | Gold (dbt marts) | Planejado |
| **E5** | Matriz de treino e modelos | Planejado |
| **E6** | Publicação para o painel | Planejado |
| **E7** | Referência e transacional (Postgres) | Em uso |

---

## Origem, destino e ferramenta

| # | Origem | Destino | Ferramenta prevista |
|---|---|---|---|
| E1 | 6 APIs externas: SIDRA/IBGE, BCB (Olinda e SGS), Alpha Vantage, Banco Mundial, DIEESE (HTML), INMET | `data/raw/<fonte>/*.json.gz` \| `*.html.gz` | Python (`httpx`, `requests`) + Dagster |
| E2 | Camada Raw | `data/parquet/<fonte>/*.parquet` | `pandas`, `pyarrow` + Dagster |
| E3 | Camada Bronze (Parquet, via `read_parquet()`) | Schema `silver` no DuckDB | dbt-duckdb (`models/staging/`) |
| E4 | Schema `silver` | Schema `gold` no DuckDB | dbt-duckdb (`models/marts/`) |
| E5 | Schema `gold` | Modelo treinado + métricas | Jupyter, `scikit-learn`, MLflow |
| E6 | Schema `gold` | Cópia publicada do DuckDB (leitura) | Dagster (asset de publicação) → Streamlit + Plotly |
| E7 | SIDRA/IBGE + escrita do lojista na aplicação | PostgreSQL 16 (referência do IPCA + transacional) | Python + `psycopg`, migrations SQL |

## Transformações e modo de execução

| # | Transformações aplicadas | ETL ou ELT | Lote ou contínuo | Frequência |
|---|---|---|---|---|
| E1 | **Nenhuma.** Grava o payload exatamente como veio, só comprimido | — (só Extract + Load) | Lote | Diária (BCB, Alpha Vantage, INMET) · Mensal (IPCA, DIEESE) · Trimestral (PIB) · Anual (PIB da China) |
| E2 | Parsing, tipagem, acréscimo de `data_ingestao` e procedência | **ELT** — carrega cru e transforma depois | Lote | Igual à E1 (mesmo asset dispara) |
| E3 | Limpar, validar, deduplicar, normalizar unidade, completar calendário civil (*forward fill*), resolver chaves | **ELT** | Lote | Disparada pelo *upstream* (E2) |
| E4 | Juntar as 8 fontes, agregar por período e cesta, calcular métricas derivadas e dimensão de variação lenta | **ELT** | Lote | Disparada pelo *upstream* (E3) |
| E5 | Montar janelas temporais, *lags*, normalização de features, divisão treino/teste | **ELT** | Lote | Sob demanda (reexperimentação) |
| E6 | Nenhuma transformação — cópia consistente, para não disputar o escritor único do DuckDB | — | Lote | Após cada materialização da Gold |
| E7 | Validar, deduplicar e resolver FK `produto.codigo_subitem_ipca`; escrita do reajuste é transacional | **ETL** na referência · escrita transacional no lojista | Lote (referência) · Contínuo (escrita do lojista) | Mensal (referência) · A cada operação (lojista) |

!!! note "Por que ELT no analítico e ETL no transacional"
    No analítico, guardar o cru custa pouco (gzip comprime ~18× no SIDRA) e permite reprocessar uma regra errada sem chamar a API de novo. No transacional, o dado precisa estar válido **antes** de entrar: uma FK quebrada derruba a aplicação do reajuste.

## Operação: atraso, responsável e detecção de falha

| # | Custo de 1 hora de atraso | Responsável na equipe | Como a equipe sabe que falhou |
|---|---|---|---|
| E1 | **Baixo.** Séries oficiais são mensais ou diárias com defasagem; 1 h não muda nenhuma decisão. *Exceção:* Alpha Vantage tem cota de 25 requisições/dia — atrasar para depois da cota empurra a coleta para o dia seguinte | Trilha de Ingestão | Código de saída ≠ 0 (erro HTTP, payload inesperado, resposta vazia — que **não** é tratada como sucesso); no Dagster, asset não materializado + alerta de frescor |
| E2 | **Baixo.** Só atrasa o que vem depois; o Raw já está salvo e o reprocesso é local | Trilha de Ingestão | Exceção de parsing/esquema encerra o asset; Parquet ausente na partição |
| E3 | **Baixo→Médio.** A Gold e o painel ficam com o dado anterior; o rótulo de data em tela deixa isso explícito | Trilha Analítica (dbt) | `dbt test` falha (unicidade, não-nulo, integridade referencial, volume, distribuição) e interrompe o *downstream* |
| E4 | **Médio.** É a camada que o lojista consulta: reajuste sugerido fica desatualizado por uma janela | Trilha Analítica (dbt) | `dbt test` nos *marts* + asset da Gold sem materializar no Dagster |
| E5 | **Nenhum.** Etapa de experimentação, fora do caminho crítico | Trilha de Machine Learning | Execução não registrada no MLflow; métrica abaixo do baseline anotado |
| E6 | **Médio.** O painel continua no ar com a cópia anterior, porém desatualizada | Trilha de Produto / Painel | Painel exibe em tela a data do último dado carregado — divergência é visível sem ferramenta |
| E7 | **Alto na escrita do lojista** (um reajuste que não grava é operação perdida) · **Baixo na referência** (mensal) | Trilha de Plataforma | Erro de transação retornado à aplicação; `just verificar-carga` confere o volume por fonte contra o esperado |
