# Taxa SELIC

Este documento registra as características arquiteturais e de negócio para a fonte de dados da taxa básica de juros da economia brasileira, extraída a partir do Sistema Gerenciador de Séries Temporais (SGS) do Banco Central do Brasil.

## Séries coletadas

A série é obtida diretamente da API do SGS (`api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados`):

| Série | Indicador | Unidade | Frequência de acesso |
|---|---|---|---|
| [11](https://www3.bcb.gov.br/sgspub/consultarvalores/telaCvsSelecionarSeries.paint) | Taxa de juros - Selic efetiva | % ao dia | Diária (dias úteis) |

!!! abstract "Decisão Arquitetural (ADR)"
    A série 11 é tratada como taxa efetiva **diária em percentual**, sem ser apresentada como taxa anualizada — a decisão está registrada no [ADR 0003](../adr/0003-bcb-macro.md), junto com o calendário civil preenchido por *forward fill* e a coluna `observado`. Isso importa porque a série 11 entrega o custo médio das operações compromissadas de um dia útil, e **não** a meta anual definida pelo Copom (série SGS 432): confundir as duas infla a taxa em duas ordens de magnitude.

O cliente ([selic_sgs.py](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/selic_sgs.py)) aceita a janela via `dataInicial`/`dataFinal`, e o ingestor ([ingest_selic.py](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/ingest_selic.py)) recua 10 dias além do início pedido para garantir que exista uma cotação anterior disponível para o preenchimento do calendário.

---

## 1. Fonte de Origem

| Atributo | Resposta |
| :--- | :--- |
| **Nome da fonte** | Banco Central do Brasil - SGS (Sistema Gerenciador de Séries Temporais), série 11 |
| **Tipo** *(usuário / sistema / interna / terceiro)* | Terceiro |
| **Quem ou o que gera** | Banco Central do Brasil (apuração do Selic/Demab a partir das operações compromissadas registradas no Sistema Especial de Liquidação e de Custódia) |
| **O que essa fonte contém** | Série histórica diária da taxa Selic efetiva, em percentual por dia útil, com data de referência no formato `DD/MM/YYYY`. |
| **Formato em que chega** *(JSON, CSV, formulário, API...)* | JSON (via API REST pública, `formato=json`) |
| **Volume estimado** *(por dia ou por mês)* | 1 requisição por rodada de carga. A janela padrão (2020 até hoje) devolve ~1.700 observações em poucas centenas de KB; em regime incremental o dado novo é 1 observação por dia útil, ou seja ~252 novos registros publicados por ano (que viram 365 linhas/ano na tabela após o preenchimento do calendário). |
| **Frequência de chegada** *(tempo real / horária / diária / eventual)* | Diária (apenas dias úteis; a publicação de um dia ocorre no dia útil seguinte) |
| **Vazão** *(alta / média / baixa)* | Baixa |
| **Pureza** *(alta / média / baixa)* | Alta (uma observação por dia útil, sem lacunas dentro do calendário bancário e sem valores sentinela; a única assimetria é a ausência de fins de semana e feriados, tratada com `ffill()` na transformação) |
| **Previsibilidade do formato** *(alta / média / baixa)* | Alta (contrato estável do SGS: lista de objetos com as chaves `data` e `valor`; o ingestor valida a presença de ambas antes de transformar) |
| **Contém dado pessoal?** *(sim / não)* | Não |
| **Base legal LGPD** *(se contém dado pessoal)* | Não se aplica |
| **Retenção** *(por quanto tempo guardar)* | Permanente (o histórico longo da Selic é necessário para o modelo captar ciclos de aperto e afrouxamento monetário, cuja defasagem sobre os preços é de vários meses) |
| **O que quebra se essa fonte falhar** | A atualização da feature de juros no banco analítico. Como a carga é reexecutável e a tabela `selic_taxa` sofre `UPSERT` por `data_referencia`, não há perda nem corrupção do histórico já carregado; os modelos passam a prever com a última taxa conhecida, perdendo sensibilidade a mudanças recentes de política monetária. Uma falha na primeira carga de um período novo é abortada explicitamente (código de saída 1) quando não existe taxa anterior para preencher o início da janela. |

---

## 2. Conjunto de Dados / Armazenamento

| Atributo | Resposta |
| :--- | :--- |
| **Conjunto de dados** | Série Histórica da Taxa Selic Efetiva Diária (Raw / Silver) |
| **Fonte de origem** *(nº da aba 1)* | Banco Central do Brasil - SGS série 11 |
| **Formato atual** | `.json.gz` na camada raw (`data/raw/bcb/selic_<inicio>_a_<fim>.json.gz`) e tabela `selic_taxa` no banco analítico embutido `DuckDB` (`data/duckdb/inflatrack.duckdb`). Não há camada Parquet intermediária: a transformação ocorre em memória com Pandas entre o raw e o DuckDB. |
| **Texto ou binário** | Binário (o raw é texto JSON comprimido em gzip; o DuckDB é formato binário colunar) |
| **Orientação** *(linha / coluna / não se aplica)* | Coluna (o DuckDB armazena `selic_taxa` em blocos colunares; o raw JSON é orientado a registro/linha) |
| **Tamanho estimado** *(em 1 ano)* | Silver: ~365 linhas/ano × 13 bytes úteis por linha (`DATE` + `DOUBLE` + `BOOLEAN`) = poucos KB/ano, desprezível. Raw: cada rodada arquiva a janela inteira (~15 KB comprimidos hoje), então rodar todo dia útil acumula ~4 MB/ano em arquivos históricos redundantes. |
| **Como é lido** *(registro inteiro / poucas colunas / busca por chave)* | Registro inteiro em recortes temporais (a tabela tem 3 colunas, então ler "poucas colunas" e ler o registro inteiro coincidem) e busca por chave em `data_referencia` nos `joins` com as demais séries macro. |
| **Frequência de leitura** | Alta (a série é lida em quase todo notebook de treino e backtesting, e participa do `join` diário com `dolar_cotacao` e com as vendas do lojista). A leitura é local, não consome a API. |
| **Formato proposto** | Manter: raw `.json.gz` para rastreabilidade e a tabela `selic_taxa` no DuckDB como camada silver consultável. |
| **Justificativa da escolha** | A série tem uma única métrica numérica por dia, então não há ganho em inserir uma camada Parquet entre o raw e o banco: o payload cabe em memória e a transformação é um `ffill()` sobre um `date_range`. O DuckDB embarcado dá SQL analítico e `UPSERT` idempotente por `data_referencia` sem servidor, e o `.json.gz` preserva a resposta original do BCB para auditoria e reprocessamento — a Squad consegue reconstruir a tabela do zero sem chamar a API de novo. |
| **Ganho esperado** *(se houver troca)* | Não há troca de formato prevista. O ganho disponível é operacional: gravar o raw em arquivos particionados por ano (ou sobrescrever um único arquivo canônico) elimina a redundância dos ~4 MB/ano de janelas repetidas. |

Detalhamento campo a campo das tabelas: [Dicionário de Dados — Macroeconomia (BCB)](../dicionario/macroeconomia.md).

---

## 3. Carga de trabalho

### Taxa de escrita

- **Carga histórica:** um evento, **1 requisição**. A janela padrão (`--de 2020-01-01 --ate hoje`) devolve a série inteira de uma vez (~1.700 observações de dias úteis) e é totalmente reexecutável.
- **Regime:** 1 observação nova publicada por dia útil (~252/ano), que o preenchimento de calendário transforma em ~365 linhas/ano na tabela `selic_taxa`.
- **Escrita real vs. custo de coleta:** o ingestor reconstrói o calendário civil completo da janela pedida e faz `UPSERT` de **todas** as linhas, não apenas das novas. Com a janela padrão, cada rodada grava ~2.460 linhas para incorporar 1 dado novo, e arquiva de novo o `.json.gz` da janela inteira. O custo é irrelevante na escala atual (a operação leva milissegundos no DuckDB), mas cresce linearmente com o tamanho do histórico.
- **Escrita transacional:** nenhuma. A carga é em lote, idempotente por `data_referencia` (`ON CONFLICT DO UPDATE`), e reexecutá-la com a mesma janela converge para o mesmo estado. Não há exigência de atomicidade com a carga do Dólar: as duas séries são escritas por scripts independentes, em tabelas independentes.
- **Recuo defensivo:** o cliente busca 10 dias antes do início pedido para ter uma cotação anterior disponível. Esses dias extras entram na resposta e no arquivo raw, mas são descartados na etapa de `reindex` e não chegam à tabela.

### Taxa de leitura e padrão de acesso

| # | Consulta | Frequência | Tipo | Acesso |
|---|---|---|---|---|
| 1 | Coleta na API do SGS (série 11) | 1 requisição/rodada (até 2 chamadas em caso de falha transitória) | lote | janela inteira em uma resposta |
| 2 | Recorte temporal da Selic para treino/backtesting | alta, sob demanda (notebooks) | pontual | filtro por faixa de `data_referencia` em `selic_taxa` |
| 3 | `Join` diário com as demais séries macro e com as vendas do lojista | alta, sob demanda | agregada | `JOIN` por `data_referencia` entre `selic_taxa` e `dolar_cotacao` |
| 4 | Auditoria de cobertura (quais dias são publicação real) | baixa, eventual | pontual | filtro por `observado = false` |

A leitura da **origem** é a menor de todas as fontes do projeto: uma requisição por rodada. A leitura do **armazenamento** domina, mas é local (DuckDB embarcado), não passa pela rede e não tem cota.

---

## 4. Restrições que a origem impõe

- **Sem autenticação e sem cota documentada,** mas também sem garantia de disponibilidade. O SGS é um serviço público sujeito a janelas de manutenção; o cliente usa timeout de 30 s e **uma única retentativa** com 1 s de espera, depois propaga o erro e a carga termina com código de saída 1. Não há *backoff* exponencial nem fila de reprocessamento.
- **Resposta não-JSON em caso de erro:** o SGS pode devolver uma página HTML de erro com status 200. É por isso que o cliente trata `json.JSONDecodeError` como falha transitória e valida que o payload é uma lista antes de devolvê-lo (`SGSError`).
- **Formato de data próprio:** a API exige `DD/MM/YYYY` em `dataInicial`/`dataFinal` e devolve as datas no mesmo padrão. O restante do projeto trabalha em ISO (`YYYY-MM-DD`), e a conversão fica isolada no ingestor.
- **Publicação defasada:** a taxa de um dia útil só aparece no dia útil seguinte. Uma carga executada hoje não encontra o valor de hoje, e o preenchimento de calendário marca esse dia como `observado = false` até a rodada seguinte corrigi-lo.
- **Somente dias úteis:** não há observação em fins de semana e feriados bancários. Sem o `ffill()`, qualquer `join` com uma venda de sábado perderia a linha; com ele, a coluna `observado` é o único jeito de distinguir dado publicado de dado esticado.
- **A série 11 é a Selic efetiva, não a meta.** Quem precisar da meta anual definida pelo Copom tem de coletar outra série do SGS (432); converter a efetiva diária para taxa anual é composição (`(1 + taxa/100) ** 252`), não multiplicação, e essa conversão não é feita na ingestão.
- **Sem histórico anterior ao início da série.** Se a janela pedida começar antes da primeira observação disponível, não existe valor anterior para preencher o início e a carga aborta com erro explícito em vez de gravar uma tabela com lacunas.
