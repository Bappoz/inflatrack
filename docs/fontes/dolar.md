# Dólar Comercial

Este documento registra as características arquiteturais e de negócio para a fonte de dados do câmbio comercial, extraída a partir da API Olinda/PTAX do Banco Central do Brasil.

## Séries coletadas

A série é obtida diretamente do serviço OData Olinda (`olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata`):

| Endpoint | Indicador | Colunas úteis | Unidade | Frequência de acesso |
|---|---|---|---|---|
| [CotacaoDolarPeriodo](https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/aplicacao#!/recursos) | Cotação PTAX do Dólar dos EUA | `cotacaoCompra`, `cotacaoVenda`, `dataHoraCotacao` | BRL por USD | Diária (dias úteis) |

!!! abstract "Decisão Arquitetural (ADR)"
    Abandonamos o uso do SGS para o Dólar (que entregava apenas uma média genérica) e migramos para a API **Olinda**. A API Olinda entrega as colunas de "Compra" e "Venda" separadas. Isso é vital, pois o repasse de inflação que atinge o lojista importador de matérias-primas está diretamente atrelado ao Dólar de *Venda*.

Essa troca de API não tem ADR próprio ainda; o [ADR 0003](../adr/0003-bcb-macro.md) cobre a outra decisão que molda esta fonte — manter uma linha por dia civil com *forward fill* e marcar as linhas preenchidas com `observado = false`. O cliente ([dolar_olinda.py](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/dolar_olinda.py)) recebe a janela e o ingestor ([ingest_dolar.py](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/ingest_dolar.py)) recua 10 dias além do início pedido para garantir uma cotação anterior disponível para o preenchimento do calendário.

---

## 1. Fonte de Origem

| Atributo | Resposta |
| :--- | :--- |
| **Nome da fonte** | Banco Central do Brasil - API Olinda/PTAX, recurso `CotacaoDolarPeriodo` |
| **Tipo** *(usuário / sistema / interna / terceiro)* | Terceiro |
| **Quem ou o que gera** | Banco Central do Brasil (a PTAX é apurada a partir das consultas do BCB aos dealers de câmbio ao longo do dia e publicada em boletins) |
| **O que essa fonte contém** | Cotações de compra e de venda do dólar americano por boletim, com o instante da apuração (`dataHoraCotacao`) e o tipo de boletim. Pode haver **mais de um boletim por dia** (abertura, intermediários e fechamento). |
| **Formato em que chega** *(JSON, CSV, formulário, API...)* | JSON (via API REST OData, `$format=json`; a carga vem embrulhada na chave `value`) |
| **Volume estimado** *(por dia ou por mês)* | 1 requisição por rodada de carga. A janela padrão (2020 até hoje) devolve alguns milhares de boletins — mais de uma linha por dia útil — em algumas centenas de KB; em regime incremental o dado novo é um punhado de boletins por dia útil, dos quais **um** sobrevive à deduplicação, gerando ~252 registros publicados por ano (365 linhas/ano na tabela após o preenchimento do calendário). |
| **Frequência de chegada** *(tempo real / horária / diária / eventual)* | Diária, com vários boletins intradiários em dias úteis (o fechamento é o que interessa ao projeto) |
| **Vazão** *(alta / média / baixa)* | Baixa |
| **Pureza** *(alta / média / baixa)* | Média (o payload é bem estruturado e sem valores sentinela, mas exige duas correções antes do uso: deduplicar os múltiplos boletins do mesmo dia mantendo o mais recente, e esticar o calendário sobre fins de semana e feriados com `ffill()`) |
| **Previsibilidade do formato** *(alta / média / baixa)* | Alta (contrato OData estável; o cliente valida que a resposta é um objeto com a lista `value` e o ingestor valida a presença de `dataHoraCotacao`, `cotacaoCompra` e `cotacaoVenda` antes de transformar) |
| **Contém dado pessoal?** *(sim / não)* | Não |
| **Base legal LGPD** *(se contém dado pessoal)* | Não se aplica |
| **Retenção** *(por quanto tempo guardar)* | Permanente (o câmbio é a principal ponte entre preços internacionais e o IPCA; o histórico longo é necessário para o modelo estimar a defasagem do repasse cambial aos preços ao consumidor) |
| **O que quebra se essa fonte falhar** | A atualização da feature de câmbio no banco analítico. A carga é reexecutável e a tabela `dolar_cotacao` sofre `UPSERT` por `data_referencia`, então não há perda nem corrupção do histórico já carregado; os modelos passam a prever com a última cotação conhecida, o que degrada rápido em período de volatilidade cambial — é a fonte em que a defasagem custa mais poder preditivo. Uma falha na primeira carga de um período novo é abortada explicitamente (código de saída 1) quando não existe cotação anterior para preencher o início da janela. |

---

## 2. Conjunto de Dados / Armazenamento

| Atributo | Resposta |
| :--- | :--- |
| **Conjunto de dados** | Série Histórica da Cotação Diária do Dólar Comercial (Raw / Silver) |
| **Fonte de origem** *(nº da aba 1)* | Banco Central do Brasil - API Olinda/PTAX |
| **Formato atual** | `.json.gz` na camada raw (`data/raw/bcb/dolar_<inicio>_a_<fim>.json.gz`) e tabela `dolar_cotacao` no banco analítico embutido `DuckDB` (`data/duckdb/inflatrack.duckdb`). Não há camada Parquet intermediária: a transformação ocorre em memória com Pandas entre o raw e o DuckDB. |
| **Texto ou binário** | Binário (o raw é texto JSON comprimido em gzip; o DuckDB é formato binário colunar) |
| **Orientação** *(linha / coluna / não se aplica)* | Coluna (o DuckDB armazena `dolar_cotacao` em blocos colunares; o raw JSON é orientado a registro/linha) |
| **Tamanho estimado** *(em 1 ano)* | Silver: ~365 linhas/ano × 21 bytes úteis por linha (`DATE` + 2 × `DOUBLE` + `BOOLEAN`) = poucos KB/ano, desprezível. Raw: cada rodada arquiva a janela inteira com **todos os boletins**, inclusive os que a deduplicação vai descartar; rodar todo dia útil acumula alguns MB/ano em arquivos históricos redundantes. |
| **Como é lido** *(registro inteiro / poucas colunas / busca por chave)* | Registro inteiro em recortes temporais e busca por chave em `data_referencia` nos `joins`. Parte das leituras usa **poucas colunas**: o modelo costuma pedir só `cotacao_venda`, e a `cotacao_compra` fica disponível para análise de spread. |
| **Frequência de leitura** | Alta (lida em quase todo notebook de treino e backtesting, e participa do `join` diário com `selic_taxa` e com as vendas do lojista). A leitura é local, não consome a API. |
| **Formato proposto** | Manter: raw `.json.gz` para rastreabilidade e a tabela `dolar_cotacao` no DuckDB como camada silver consultável. |
| **Justificativa da escolha** | São duas métricas numéricas por dia; o payload cabe em memória e a transformação é uma deduplicação mais um `ffill()` sobre um `date_range`, então uma camada Parquet entre o raw e o banco não pagaria seu custo. O DuckDB embarcado dá SQL analítico e `UPSERT` idempotente por `data_referencia` sem servidor, e o `.json.gz` preserva a resposta original do BCB — inclusive os boletins intradiários descartados, o que permite auditar a escolha do fechamento e reprocessar sem chamar a API de novo. |
| **Ganho esperado** *(se houver troca)* | Não há troca de formato prevista. O ganho disponível é operacional: particionar o raw por ano (ou manter um arquivo canônico sobrescrito) elimina a redundância das janelas repetidas, que aqui pesa mais que na Selic porque o arquivo guarda todos os boletins do período. |

---

## 3. Carga de trabalho

### Taxa de escrita

- **Carga histórica:** um evento, **1 requisição**. O recurso `CotacaoDolarPeriodo` aceita a janela inteira e devolve todos os boletins de uma vez; a carga é totalmente reexecutável.
- **Regime:** um punhado de boletins novos por dia útil, reduzidos a 1 registro por dia pela deduplicação (~252/ano), que o preenchimento de calendário transforma em ~365 linhas/ano na tabela `dolar_cotacao`.
- **Escrita real vs. custo de coleta:** o ingestor reconstrói o calendário civil completo da janela pedida e faz `UPSERT` de **todas** as linhas, não apenas das novas. Com a janela padrão, cada rodada grava ~2.460 linhas para incorporar 1 dado novo, e arquiva de novo o `.json.gz` da janela completa. Irrelevante na escala atual, mas cresce linearmente com o histórico.
- **Escrita transacional:** nenhuma. A carga é em lote, idempotente por `data_referencia` (`ON CONFLICT DO UPDATE`), e reexecutá-la com a mesma janela converge para o mesmo estado. Não há exigência de atomicidade com a carga da Selic: são scripts e tabelas independentes.
- **Descarte na transformação:** os boletins intradiários e os 10 dias de recuo defensivo entram no arquivo raw, mas não chegam à tabela — o volume escrito é bem menor que o coletado.

### Taxa de leitura e padrão de acesso

| # | Consulta | Frequência | Tipo | Acesso |
|---|---|---|---|---|
| 1 | Coleta na API Olinda (`CotacaoDolarPeriodo`) | 1 requisição/rodada (até 2 chamadas em caso de falha transitória) | lote | janela inteira em uma resposta |
| 2 | Recorte temporal do dólar de venda para treino/backtesting | alta, sob demanda (notebooks) | pontual | filtro por faixa de `data_referencia`, projetando `cotacao_venda` |
| 3 | `Join` diário com as demais séries macro e com as vendas do lojista | alta, sob demanda | agregada | `JOIN` por `data_referencia` entre `dolar_cotacao` e `selic_taxa` |
| 4 | Análise de spread compra/venda | baixa, eventual | agregada | `cotacao_venda - cotacao_compra` sobre a série |
| 5 | Auditoria de cobertura (quais dias são publicação real) | baixa, eventual | pontual | filtro por `observado = false` |

A leitura da **origem** é de uma requisição por rodada. A leitura do **armazenamento** domina, mas é local (DuckDB embarcado), não passa pela rede e não tem cota.

---

## 4. Restrições que a origem impõe

- **Sem autenticação e sem cota documentada,** mas também sem garantia de disponibilidade. O Olinda é um serviço público sujeito a manutenção e a throttling não documentado; o cliente usa timeout de 30 s e **uma única retentativa** com 1 s de espera, depois propaga o erro e a carga termina com código de saída 1. Não há *backoff* exponencial nem fila de reprocessamento.
- **Formato de data americano e obrigatório:** os parâmetros `@dataInicial` e `@dataFinalCotacao` exigem `MM-DD-YYYY` entre aspas simples dentro do próprio valor. Não há como pedir a série sem janela, e o restante do projeto trabalha em ISO (`YYYY-MM-DD`), então a conversão fica isolada no cliente.
- **Resposta embrulhada em OData:** os registros não vêm na raiz, e sim na chave `value`. Uma resposta de erro pode não ter essa chave, por isso o cliente valida a estrutura e levanta `OlindaError`.
- **Mais de um boletim por dia:** o recurso devolve abertura, intermediários e fechamento. Sem a deduplicação por `dataHoraCotacao` (mantendo o último), a tabela ganharia linhas conflitantes para a mesma data — é uma correção obrigatória, não uma otimização.
- **Somente dias úteis:** não há boletim em fins de semana e feriados bancários. Sem o `ffill()`, um `join` com uma venda de sábado perderia a linha; com ele, a coluna `observado` é o único jeito de distinguir cotação publicada de cotação esticada.
- **Publicação ao longo do dia:** uma carga executada antes do fechamento do câmbio pega apenas os boletins já publicados, e o valor gravado para hoje pode ser substituído na rodada seguinte. O `UPSERT` idempotente é o que torna essa correção segura.
- **A PTAX não é a cotação de mercado em tempo real.** É a taxa de referência apurada pelo BCB para o dia; quem precisar de intradiário de mercado precisa de outra fonte, fora do Banco Central.
- **Sem histórico anterior ao início da série.** Se a janela pedida começar antes da primeira cotação disponível, não existe valor anterior para preencher o início e a carga aborta com erro explícito em vez de gravar uma tabela com lacunas.
