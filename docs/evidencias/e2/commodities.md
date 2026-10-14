# Evidência E2 — Commodities (Alpha Vantage)

Executado em **2026-10-13** contra a API da Alpha Vantage (`deltalake` 1.6.6, `duckdb` 1.5.5). As duas execuções completas gastaram 18 das 25 requisições do dia.

!!! info "Onde está o código"
    [`ingest_commodities.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/ingest_commodities.py) (validação, transformação, checagens, gravação e importação), usando o helper comum [`bronze.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/bronze.py). Testes em `tests/test_commodities.py`, com recortes de respostas reais de WTI e CORN em `tests/fixtures/commodities/`.

## Situação das tarefas da E2

| Tarefa | Situação |
|---|---|
| Parar de engolir erros | Feita |
| `commodities_resposta` e `commodities_cotacao` em Delta, com as linhas `"."` e `name`, `interval`, `unit` | Feita |
| Importar `data/raw/commodities_raw/` | Feita: 9 arquivos |
| Demonstração de reexecução | Feita |
| Política de dado atrasado | Feita |
| Checagens: 9 símbolos, `(symbol, data_referencia)` único, volume de referência | Feitas |
| Diário de bordo das Semanas 7 a 10 | **Pendente** (texto pessoal) |

## Como reproduzir

```bash
just bronze-commodities-importar   # Raw antigo -> Delta, sem gastar cota
just bronze-commodities            # 9 requisições, ~1 min 45 s
just bronze-commodities            # de novo: nada novo
just bronze-commodities-checar
```

Precisa de `ALPHAVANTAGE_API_KEY` no `.env`. A chave **não** é guardada: `_requisicao` traz só `function` e `interval`.

## Erros que agora falham

Antes, o erro era só registrado no log e a execução terminava com sucesso. Agora a série com problema não é gravada em nenhum destino, e o ingestor sai com código 1, o que faz o asset do Dagster falhar.

| Resposta da API | Resultado |
|---|---|
| HTTP de erro | Falha |
| Status 200 com `Information` (cota esgotada) ou `Note` | Falha, e as séries seguintes não são pedidas, para não gastar cota |
| Status 200 com `Error Message` | Falha |
| Sem o campo `data`, ou `data` vazia | Falha |
| `interval` diferente do pedido | Falha |
| Menos linhas que o mínimo de referência, ou data repetida | Falha |

A mensagem de cota esgotada dos testes segue o formato da documentação. Ela **não** foi capturada de uma resposta real, porque a cota não esgotou nesta sessão.

## O que é gravado

| Tabela | Uma linha por | Volume |
|---|---|---|
| `commodities_resposta` | Resposta diferente | 18 (9 importadas + 9 baixadas) |
| `commodities_cotacao` | Data da série, particionada por `symbol`, **inclusive as datas com `"."`** (`preco` nulo) | 31.880 |

A série chega inteira a cada chamada. Por isso a partição do símbolo é **substituída** quando a resposta muda, e fica como está quando a resposta é igual. Cada versão anterior continua na tabela de respostas.

## Demonstração de reexecução

| Momento | `resposta` (versão / linhas) | `cotacao` (versão / linhas) |
|---|---|---|
| Depois da importação | 8 / 9 | 8 / 31.850 |
| Depois da 1ª execução | 17 / 18 | 17 / 31.880 |
| Depois da 2ª execução | **17 / 18** | **17 / 31.880** |

```text
WTI: 10634 linhas; resposta já guardada; partição mantida
BRENT: 10275 linhas; resposta já guardada; partição mantida
...
ALL_COMMODITIES: 415 linhas; resposta já guardada; partição mantida
```

Na 1ª execução, as três séries diárias ganharam 10 datas cada. As seis mensais trouxeram os mesmos dados, mas o corpo importado é o JSON regravado pelo ingestor antigo, e por isso o hash é outro. Na 2ª execução, as **9 respostas eram idênticas**, e o hash evitou as 9 gravações.

## Política de dado atrasado

| Situação | O que o pipeline faz |
|---|---|
| Série atualizada | A série inteira é relida a cada execução; a partição do símbolo passa a apontar para a resposta nova |
| Valor antigo revisado | Fica visível comparando as versões em `commodities_resposta` |
| Cota esgotada | A execução falha; o agendamento diário tenta no dia seguinte |

!!! warning "Atraso medido maior que o do plano"
    Em 2026-10-13, a última data do WTI era **2026-10-06** (7 dias), e a das séries mensais era **2026-07-01** (3 meses). O freshness "D+2" proposto no plano (seção 2.5) não se sustenta para energia.

## Checagens

`just bronze-commodities-checar`:

```text
symbol=ALL_COMMODITIES linhas=415 datas_repetidas=0 sem_preco=0 preco_nao_positivo=0 ...
symbol=BRENT linhas=10275 datas_repetidas=0 sem_preco=1173 preco_nao_positivo=0 ...
symbol=COFFEE linhas=559 datas_repetidas=0 sem_preco=144 preco_nao_positivo=0 ...
symbol=NATURAL_GAS linhas=7761 datas_repetidas=0 sem_preco=2059 preco_nao_positivo=0 ...
symbol=WTI linhas=10634 datas_repetidas=0 sem_preco=1117 preco_nao_positivo=1 ...
symbols=9 linhas=31880
```

**Volume de referência.** Na importação, a tabela tinha 31.850 linhas, das quais **26.781** com preço: exatamente o número do plano. A diferença são as 5.069 datas com `"."`, que o caminho antigo descartava.

**Preço ≤ 0.** O WTI tem um preço negativo real: −36,98 em 2020-04-20. A Bronze o mantém. O teste de distribuição do dbt (E3) precisa tratar esse caso, em vez de descartá-lo sem aviso.

## Medições para o ADR 0004

| Onde | Tamanho |
|---|---|
| `data/raw/commodities_raw/` (9 `.json.gz`) | 166 KB |
| `commodities_resposta` (18 respostas, snappy) | 714 KB; corpos somam 4,0 MB sem compressão |
| `commodities_cotacao` (9 arquivos ativos) | 774 KB em disco, com os 9 arquivos substituídos |

Cada substituição de partição deixa o arquivo antigo no disco até um `VACUUM`. Na tabela de cotações isso é permitido; na tabela de respostas, não.

**Compressão.** Cada tabela regravada num único Parquet por codec; leitura de todas as linhas pelo DuckDB, melhor de 3.

| Tabela | snappy | zstd | gzip |
|---|---|---|---|
| `commodities_resposta` (18) | 598 KB, 8 ms | 335 KB, 9 ms | 339 KB, 11 ms |
| `commodities_cotacao` (31.880) | 240 KB, 279 ms | 208 KB, 287 ms | 194 KB, 287 ms |

O zstd ocupa ~45% menos que o snappy na tabela de respostas com o mesmo tempo de leitura. As tabelas estão em snappy, o padrão do `deltalake`.

**Respostas que o hash evitou.** Medido só num dia (2026-10-13), e não numa semana: na reexecução, 9 de 9 respostas eram iguais às já guardadas. A medição de uma semana continua pendente.
