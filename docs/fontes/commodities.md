# Commodities e Energia

Este documento registra as características arquiteturais e de negócio para a fonte de dados de commodities globais, extraída a partir da Alpha Vantage.

## Séries coletadas

Todas as séries são obtidas diretamente da API da Alpha Vantage (`www.alphavantage.co`):

| Função | Commodity | Unidade | Frequência de acesso |
|---|---|---|---|
| [WTI](https://www.alphavantage.co/documentation/#crude-oil-wti) | Petróleo WTI | USD/barril | Diária |
| [BRENT](https://www.alphavantage.co/documentation/#crude-oil-brent) | Petróleo Brent | USD/barril | Diária |
| [NATURAL_GAS](https://www.alphavantage.co/documentation/#natural-gas) | Gás Natural | USD/MMBtu | Diária |
| [WHEAT](https://www.alphavantage.co/documentation/#wheat) | Trigo | USD/tonelada métrica | Mensal |
| [CORN](https://www.alphavantage.co/documentation/#corn) | Milho | USD/tonelada métrica | Mensal |
| [COTTON](https://www.alphavantage.co/documentation/#cotton) | Algodão | USD/tonelada métrica | Mensal |
| [SUGAR](https://www.alphavantage.co/documentation/#sugar) | Açúcar | centavos/libra | Mensal |
| [COFFEE](https://www.alphavantage.co/documentation/#coffee) | Café | centavos/libra | Mensal |
| [ALL_COMMODITIES](https://www.alphavantage.co/documentation/#commodities) | Índice Global de Commodities | índice (2016 = 100%) | Mensal |

---

## 1. Fonte de Origem

| Atributo | Resposta |
| :--- | :--- |
| **Nome da fonte** | Alpha Vantage - API de Commodities e Energia |
| **Tipo** *(usuário / sistema / interna / terceiro)* | Terceiro |
| **Quem ou o que gera** | Alpha Vantage (agregando dados de bolsas de valores globais, FMI e relatórios do FRED) |
| **O que essa fonte contém** | Séries históricas de preços de energia (Petróleo WTI, Brent, Gás Natural) e agrícolas (Trigo, Milho, Algodão, Açúcar, Café, Índice Global). |
| **Formato em que chega** *(JSON, CSV, formulário, API...)* | JSON (via API REST) |
| **Volume estimado** *(por dia ou por mês)* | ~9 requisições diárias. Em tamanho, a carga incremental traz poucos KBs por dia. Em volume de dados anual, geramos aprox. 822 novos registros/ano (750 dias úteis das energias + 72 meses dos agrícolas). |
| **Frequência de chegada** *(tempo real / horária / diária / eventual)* | Diária (para energia) e Mensal (para agrícolas e índices) |
| **Vazão** *(alta / média / baixa)* | Baixa |
| **Pureza** *(alta / média / baixa)* | Média (possui assimetrias de calendário, como fins de semana e feriados sem cotação que necessitam de imputação posterior, mas o payload JSON é perfeitamente estruturado) |
| **Previsibilidade do formato** *(alta / média / baixa)* | Alta (Schema fixo mantido pela Alpha Vantage) |
| **Contém dado pessoal?** *(sim / não)* | Não |
| **Base legal LGPD** *(se contém dado pessoal)* | Não se aplica |
| **Retenção** *(por quanto tempo guardar)* | Permanente (o modelo preditivo de IPCA necessita do histórico mais longo possível para capturar sazonalidades longas e tendências macroeconômicas) |
| **O que quebra se essa fonte falhar** | A atualização das features no banco. Os modelos de ML passarão a prever usando as últimas cotações conhecidas (defasadas), perdendo poder preditivo com o passar dos dias, mas não há quebra de integridade no banco de dados analítico. |

---

## 2. Conjunto de Dados / Armazenamento

| Atributo | Resposta |
| :--- | :--- |
| **Conjunto de dados** | Cotações Históricas de Commodities (Raw / Silver / Gold) |
| **Fonte de origem** *(nº da aba 1)* | Alpha Vantage |
| **Formato atual** | `.parquet` (Raw) carregado em base embutida `DuckDB` |
| **Texto ou binário** | Binário |
| **Orientação** *(linha / coluna / não se aplica)* | Linha (na tabela física `commodity_cotacao`) com leitura transposta em Coluna (nas Views PIVOT, para machine learning) |
| **Tamanho estimado** *(em 1 ano)* | < 1 MB / ano (séries temporais numéricas extremamente leves) |
| **Como é lido** *(registro inteiro / poucas colunas / busca por chave)* | Busca de recortes temporais completos da série / Registro Inteiro |
| **Frequência de leitura** | Alta (acessado frequentemente nos Jupyter Notebooks durante treinamento e backtesting dos modelos de regressão) |
| **Formato proposto** | Manter em disco como Parquet (camada bronze) e carga transacional-analítica embarcada no DuckDB. |
| **Justificativa da escolha** | A tabela principal `commodity_cotacao` segue o formato longo (Tall), permitindo adição fácil de novas commodities sem quebrar schemas (flexibilidade típica de Data Engineering). Ao mesmo tempo, a modelagem via DuckDB fornece o processamento OLAP super-rápido para transpor os dados (Wide format) diretamente em Views locais (`vw_features_daily` e `vw_features_monthly`), poupando os Cientistas de Dados do esforço inicial de pivotamento manual. |
| **Ganho esperado** *(se houver troca)* | Agrega a flexibilidade e escalabilidade do modelo dimensional (sem necessidade de um DW pesado em nuvem) com o ecossistema Python local, suportando imputações (`.ffill()`) nativas no Pandas em milissegundos a partir da conexão direta DuckDB -> Pandas DataFrame. |

---

## 3. Carga de trabalho

### Taxa de escrita

- **Carga histórica:** um evento, 9 requisições (uma por série), reexecutável. A API devolve a série inteira a cada chamada, então o histórico completo cabe em uma única rodada.
- **Regime:** ~822 registros novos por ano (~750 das 3 séries diárias em dias úteis + 72 das 6 séries mensais). Em média, 3 linhas por dia útil; no dia de fechamento do mês, mais 6.
- **Escrita real vs. custo de coleta:** o cliente ([alphavantage.py](../../src/inflatrack/alphavantage.py)) não filtra por data, então cada rodada baixa a série completa e o Parquet da camada bronze é sobrescrito. O volume de escrita útil é minúsculo, mas o volume trafegado é o histórico inteiro a cada execução.
- **Escrita transacional:** nenhuma. A carga é em lote e reexecutável, sem exigência de atomicidade entre séries.

### Taxa de leitura e padrão de acesso

| # | Consulta | Frequência | Tipo | Acesso |
|---|---|---|---|---|
| 1 | Coleta na API da Alpha Vantage | 1 rodada/dia = 9 requisições | lote | 1 requisição por série, série completa |
| 2 | Recorte temporal de uma commodity para treino/backtesting | alta, sob demanda (notebooks) | pontual | filtro por (`symbol`, `data_referencia`) em `commodity_cotacao` |
| 3 | Matriz de features para o modelo | alta, sob demanda (notebooks) | agregada | `SELECT *` em `vw_features_daily` ou `vw_features_monthly` (PIVOT) |

A leitura da **origem** é baixa e previsível (9 requisições/dia). A leitura do **armazenamento** é o que domina, mas é local (DuckDB embarcado), não passa pela API e não consome cota.

---

## 4. Restrições que a origem impõe

- **Cota diária de 25 requisições no plano gratuito** ([página de suporte](https://www.alphavantage.co/support/#support)). Uma rodada completa gasta 9, deixando margem para ~2 rodadas e meia por dia. Reexecuções, testes e retentativas consomem da mesma cota, e ela não é reposta ao longo do dia.
- **Limite por minuto:** a documentação principal não o especifica para o plano gratuito. O cliente assume o valor histórico de 5 requisições/minuto e espaça as chamadas em 13 s (`_rate_limit`), o que faz uma rodada completa levar ~2 min.
- **Assimetria de calendário:** as séries diárias não têm cotação em fins de semana e feriados, e a origem pode devolver `.` no lugar do valor. O ingestor descarta esses registros, e a imputação (`.ffill()`) fica para a camada seguinte.
- **Sem filtro por data.** Não há parâmetro de janela: a resposta é sempre a série completa, então não existe carga incremental verdadeira do lado da origem, apenas do lado do armazenamento.
- **Frequências diferentes por série:** energia é diária, agrícolas e índice global são mensais. Consultar as mensais todo dia gasta cota sem trazer dado novo; só o fechamento do mês muda a série.
