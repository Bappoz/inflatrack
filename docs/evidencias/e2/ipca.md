# Evidência E2 — IPCA/INPC (SIDRA)

O que a fonte `ipca` entrega na Entrega 2, com o comando que produziu cada número. Tudo nesta página foi executado em **2026-10-11**, contra a API do SIDRA e contra o PostgreSQL do `docker compose`, no commit `4f1c78c` (`deltalake` 1.6.6, `duckdb` 1.5.5, `pyarrow` 25.0.1).

!!! info "Onde está o código"
    [`src/inflatrack/bronze_ipca.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/bronze_ipca.py) (transformação, checagens, gravação e importação), chamado por [`ingest.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/ingest.py) a cada mês. Testes em `tests/test_ipca.py`, com respostas reais do SIDRA em `tests/fixtures/ipca/`. Colunas das duas tabelas no [Dicionário de Dados](../../dicionario/sidra.md#bronze-em-delta).

## Situação das tarefas da E2

Itens da seção 3.1 das tasks que o grupo separou.

| Tarefa | Situação | Evidência |
|---|---|---|
| `transformar(payload)` mantendo todos os campos e todas as linhas | Feita | [Transformação](#transformacao) |
| Gravar `ipca_resposta` e `ipca_observacao` em Delta, sem tirar o Postgres | Feita | [Carga histórica](#carga-historica) |
| Importar os 886 `.json.gz` para `ipca_resposta` e extrair as observações | Feita, para os 5 agregados | [Importação do Raw](#importacao-do-raw-antigo) |
| Demonstração de reexecução | Feita | [Reexecução](#demonstracao-de-reexecucao) |
| Política de dado atrasado | Feita e implementada no agendamento | [Política](#politica-de-dado-atrasado) |
| Checagens de esquema e volume | Feitas | [Checagens](#checagens-de-esquema-e-volume) |
| Diário de bordo das Semanas 7 a 10 | **Pendente** | Texto pessoal de quem fez; não foi escrito nesta sessão |

## Como reproduzir

```bash
just up                                # PostgreSQL com as migrations
just bronze-ipca 2026-07 2026-09       # 3 meses do 7060: Delta + Postgres
just bronze-ipca 2026-07 2026-09       # de novo: nenhuma linha nova
just bronze-ipca-checar                # volume, meses faltando e revisões
just bronze-ipca-importar              # só para quem tem data/raw/ipca-inpc/ antigo
just test                              # 55 testes, 25 deles da Bronze do IPCA
```

`just bronze-ipca <de> <ate> [agregado]` aceita qualquer intervalo e qualquer um dos cinco agregados. A carga histórica inteira é `just seed`, que leva cerca de 21 minutos.

## Transformação

`transformar(payload, agregado)` devolve **uma linha por objeto da resposta**, na mesma ordem. Nada é descartado e nenhum valor padrão é inventado.

| Campo do SIDRA | Coluna | Conversão |
|---|---|---|
| `NC` | `nivel_territorial` | Inteiro |
| `D1C` | `codigo_localidade` | Inteiro |
| `D2C` | `codigo_variavel` | Inteiro |
| `D3C` | `mes_referencia` | `"202609"` → `2026-09-01` |
| `D4C` | `id_categoria` | Inteiro; nulo no 1737, que não tem classificação |
| `MC` | `codigo_unidade` | Inteiro; nulo quando a API manda vazio |
| `V` | `valor` | Decimal; **nulo** para `...`, `..`, `-` e `X` |
| `V` | `valor_bruto` | O texto exatamente como veio |

O que fica **fora** do ingestor e vai para o dbt: descartar marcador, interpretar o `-`, traduzir `id_categoria` para o código da cesta e unir 2938 → 1419 → 7060.

Marcadores encontrados em todo o histórico (9.116.436 linhas): `-` em 2.333.484 linhas e `...` em 790.055. Os marcadores `..` e `X`, citados na ajuda da API, **não apareceram** em nenhuma das 886 respostas; o código os reconhece e o teste os cobre com uma linha real alterada à mão.

## Carga histórica

Comando: os cinco agregados, de ponta a ponta, pelo ingestor (uma requisição por mês). Duração medida: **1.262 s (~21 min)** para 886 requisições.

| Agregado | Período | Meses | Linhas no Delta | Sem valor (marcador) | Linhas no PostgreSQL |
|---|---|---|---|---|---|
| 2938 | jul/2006 a dez/2011 | 66 | 1.104.840 | 232.350 | 872.490 |
| 1419 | jan/2012 a dez/2019 | 96 | 3.028.992 | 1.251.003 | 1.777.989 |
| 7060 | jan/2020 a set/2026 | 81 | 2.517.156 | 825.391 | 1.691.765 |
| 7063 (INPC) | jan/2020 a set/2026 | 81 | 2.462.076 | 814.772 | 1.647.304 |
| 1737 (nº-índice) | dez/1979 a set/2026 | 562 | 3.372 | 23 | 3.349 |
| **Total** | | **886** | **9.116.436** | **3.123.539** | **5.992.897** |

"Linhas no Delta" é `ipca_observacao`; "Linhas no PostgreSQL" é a tabela `observacao`. A conta fecha em todos os agregados: linhas do Delta − linhas sem valor = linhas do PostgreSQL. O Delta tem as 3.123.539 linhas que o caminho antigo descartava.

`ipca_resposta` tem **886 linhas**, uma por requisição, com 886 hashes distintos (1,29 GB de corpo antes da compressão).

## Demonstração de reexecução

A mesma partição, executada de novo, não acrescenta linha em nenhum dos três destinos, e o Delta nem cria versão nova.

```text
--- antes
resposta versao 885 linhas 886
observacao versao 885 linhas 9116436
postgres observacao|5992897
--- reexecucao: just bronze-ipca 2026-07 2026-09
INFO cesta sincronizada: 457 categorias do agregado 7060
INFO 7060/202607: bronze com 0 de 31076 linhas novas (resposta já guardada)
INFO 7060/202607: 0 linhas novas
INFO 7060/202608: bronze com 0 de 31076 linhas novas (resposta já guardada)
INFO 7060/202608: 0 linhas novas
INFO 7060/202609: bronze com 0 de 31076 linhas novas (resposta já guardada)
INFO 7060/202609: 0 linhas novas
INFO total inserido: 0 linhas
--- depois
resposta versao 885 linhas 886
observacao versao 885 linhas 9116436
postgres observacao|5992897
```

**Por que é idempotente.** A resposta só é gravada se o SHA-256 do corpo ainda não existe na tabela. A observação só é gravada se a combinação mês × localidade × variável × categoria × `valor_bruto` ainda não existe. O corpo devolvido pelo SIDRA para a mesma requisição foi idêntico byte a byte nas duas execuções.

**Semântica de entrega:** *at-least-once* na leitura (o mês é pedido de novo a cada execução) com escrita idempotente, o que resulta em **efetivamente uma vez** nas tabelas.

## Checagens de esquema e volume

A resposta do SIDRA é sempre um **retângulo completo** localidade × variável × categoria: onde não há dado, a API manda um marcador em vez de omitir a linha. Por isso o volume esperado de cada mês é exato, e não uma faixa.

| Agregado | Localidades | Variáveis | Categorias | Linhas por mês |
|---|---|---|---|---|
| 2938 | 12 | 63, 66, 69 | 465 | 16.740 |
| 1419 | 17 | 63, 66, 69, 2265 | 464 | 31.552 |
| 7060 | 17 | 63, 66, 69, 2265 | 457 | 31.076 |
| 7063 | 17 | 44, 45, 68, 2292 | 447 | 30.396 |
| 1737 | 1 | 63, 69, 2263, 2264, 2265, 2266 | — | 6 |

!!! warning "Correção ao plano"
    O plano lista as variáveis do 7060 como "63, 2265 e 2266". O medido é **63, 66, 69 e 2265**; a 2266 (número-índice) só existe no 1737.

As checagens rodam **antes de qualquer escrita**; resposta reprovada não entra em nenhuma das duas tabelas.

| Checagem | Falha quando |
|---|---|
| Esquema | Um objeto tem campo a mais ou a menos que `NC`, `MC`, `V`, `D1C`, `D2C`, `D3C`, `D4C` |
| Valor | `V` não é número nem um dos quatro marcadores |
| Não vazia | A resposta é `[]` (mês ainda não divulgado) |
| Mês | A resposta traz mais de um mês, ou um mês diferente do pedido |
| Localidades e variáveis | Diferem da tabela acima |
| Categorias | Diferem em mais de 5% da tabela acima |
| Retângulo | Alguma combinação falta ou se repete |

`just bronze-ipca-checar` confere a tabela já gravada: sequência de meses sem buraco e volume de cada mês.

```text
agregado=1419 primeiro_mes=2012-01-01 ultimo_mes=2019-12-01 meses=96 meses_faltando=0 linhas=3028992 linhas_por_mes_esperadas=31552 meses_fora_do_volume=0 linhas_de_revisao=0 linhas_sem_valor=1251003
agregado=1737 primeiro_mes=1979-12-01 ultimo_mes=2026-09-01 meses=562 meses_faltando=0 linhas=3372 linhas_por_mes_esperadas=6 meses_fora_do_volume=0 linhas_de_revisao=0 linhas_sem_valor=23
agregado=2938 primeiro_mes=2006-07-01 ultimo_mes=2011-12-01 meses=66 meses_faltando=0 linhas=1104840 linhas_por_mes_esperadas=16740 meses_fora_do_volume=0 linhas_de_revisao=0 linhas_sem_valor=232350
agregado=7060 primeiro_mes=2020-01-01 ultimo_mes=2026-09-01 meses=81 meses_faltando=0 linhas=2517156 linhas_por_mes_esperadas=31076 meses_fora_do_volume=0 linhas_de_revisao=0 linhas_sem_valor=825391
agregado=7063 primeiro_mes=2020-01-01 ultimo_mes=2026-09-01 meses=81 meses_faltando=0 linhas=2462076 linhas_por_mes_esperadas=30396 meses_fora_do_volume=0 linhas_de_revisao=0 linhas_sem_valor=814772
```

Os 886 meses passaram: nenhum faltando, nenhum fora do volume.

## Importação do Raw antigo

Para quem já tem `data/raw/ipca-inpc/` de cargas anteriores, `just bronze-ipca-importar` leva os `.json.gz` para as duas tabelas sem chamar a API. Executada sobre os **886 arquivos**, numa pasta Delta vazia:

| Execução | Respostas novas | Observações novas | Duração |
|---|---|---|---|
| 1ª | 886 | 9.116.436 | 3 min 18 s |
| 2ª (mesmos arquivos) | 0 | 0 | 4 min 38 s |

A tabela importada tem exatamente as mesmas observações da tabela gravada pelo ingestor: a diferença entre as duas, linha a linha, é **zero**.

O Raw antigo não guardou tudo. O que a importação não consegue recuperar fica nulo ou é reconstruído, e isso está dito aqui em vez de ser preenchido com um valor plausível:

| Coluna | Na importação |
|---|---|
| `corpo` | O texto do arquivo. É o JSON que o ingestor antigo **regravou**, e não os bytes originais da API |
| `hash_corpo` | Calculado sobre esse texto. Por isso difere do hash da mesma resposta baixada de novo |
| `status_http`, `tipo_conteudo` | Nulos |
| `_requisicao` | Reconstruída pelo nome do arquivo (agregado e mês) |
| `_ingerido_em` | Data de modificação do arquivo |

Consequência prática: importar o Raw **e** baixar o mesmo mês pela API guarda dois corpos para o mesmo conteúdo. As observações não se duplicam, porque são comparadas pelo valor, e não pelo hash.

## Política de dado atrasado

Texto da fonte `ipca` para o ADR 0004 (seção 2.6 das tasks que o grupo separou).

| Situação | Como a origem se comporta | O que o pipeline faz |
|---|---|---|
| **Mês ainda não divulgado** | O SIDRA responde HTTP 200 com `[]`, sem erro. Conferido em 2026-10-11: out/2026 devolve `[]` e set/2026 já está publicado | A execução **falha** antes de gravar qualquer coisa, a partição fica pendente e o agendamento tenta de novo no dia seguinte (dias 9 a 13, às 10h de Brasília) |
| **Revisão de mês já divulgado** | A API não tem filtro "o que mudou": uma revisão só é vista se o mês for baixado de novo | A cada ciclo o agendamento **relê os 3 meses anteriores** ao mês novo. O valor revisado entra como linha nova; o anterior permanece |
| **Reprocessamento manual** | — | Qualquer intervalo de partições pode ser reexecutado pelo Dagster ou por `just bronze-ipca`; reler não duplica |

A janela de releitura está em `orchestration/partitions.py` (`MESES_RELIDOS = 3`) e é exercitada por `tests/test_orchestration.py`.

**O que esta política não cobre:**

- **Divulgação depois do dia 13.** O agendamento só pede o mês anterior entre os dias 9 e 13. Se o IBGE divulgar depois disso, o mês só entra por execução manual ou como parte da releitura do ciclo seguinte.
- **Revisão com mais de 3 meses.** Não é relida automaticamente. Um backfill do intervalo resolve.
- **Frequência real das revisões.** Não foi medida: todo o histórico foi baixado numa única data, então `linhas_de_revisao` é 0 por construção. A coluna passa a medir isso a partir de agora.

## Medições para o ADR 0004

Feitas sobre as tabelas reais do IPCA, como contribuição às medições comuns da seção 4.2 das tasks que o grupo separou.

**Compressão.** A tabela inteira regravada num único Parquet por codec; leitura pelo DuckDB, melhor de 3.

| Tabela | Codec | Tamanho | Leitura no DuckDB |
|---|---|---|---|
| `ipca_resposta` (886 corpos) | snappy | 116,7 MB | 682 ms |
| | zstd | 52,2 MB | 731 ms |
| | gzip | 49,4 MB | 1.518 ms |
| `ipca_observacao` (9,1 mi linhas) | snappy | 36,2 MB | 42 ms |
| | zstd | 28,9 MB | 44 ms |
| | gzip | 28,8 MB | 43 ms |

Na tabela de respostas, o zstd ocupa menos da metade do snappy com o mesmo tempo de leitura; o gzip economiza mais 5% e dobra o tempo. O `deltalake` grava em **snappy** por padrão, e é assim que as tabelas estão hoje.

**`.json.gz` × tabela de respostas.**

| Onde | Arquivos | Tamanho |
|---|---|---|
| `data/raw/ipca-inpc/*.json.gz` | 886 | 47,0 MB |
| `ipca_resposta` em Delta (snappy, como está) | 886 | 120,4 MB |
| `ipca_resposta` em zstd (medição acima) | 1 | 52,2 MB |

**Número de arquivos.** Cada escrita no Delta cria um arquivo, então a contagem depende de quantos meses entram por escrita, e não só do esquema de partição.

| Como `ipca_observacao` foi gravada | Arquivos | Tamanho |
|---|---|---|
| Ingestor, uma escrita por mês | 886 | 66,3 MB |
| Importação, uma escrita a cada 12 meses | 75 | 56,6 MB |

A tabela é particionada só por `agregado` (5 partições). No regime mensal são 3 arquivos novos por mês; compactar (`OPTIMIZE`) periodicamente resolve o acúmulo.

## Achados e limitações

!!! warning "O PostgreSQL arredonda o número-índice antigo para zero"
    `observacao.valor` é `numeric(16,7)`. O número-índice do 1737 (base dez/1993 = 100) chega com 13 casas e é minúsculo antes do Plano Real: dez/1979 vale `0.0000000076183`. No PostgreSQL, **33 meses (dez/1979 a ago/1982) estão gravados como `0.0000000`**, e 168 valores até nov/1993 perderam casas. A Bronze guarda `decimal(28,13)` e o texto original. A consulta C3 parte de 2006 e não é afetada; qualquer razão entre índices anterior a 1994 é. Não foi corrigido nesta entrega: exige migration sobre a tabela do ADR 0001.

- **O acumulado em 12 meses do 7060 não existe em 2020.** De jan a nov/2020 a variável 2265 vem como `...` para todas as categorias (5.027 linhas só no nível Brasil). A união 1419 → 7060 no dbt precisa buscar o acumulado de 2020 em outra fonte ou derivá-lo.
- **Helper comum.** Desde 2026-10-13, `ipca_resposta` é gravada pelo helper `inflatrack/bronze.py`. `ipca_observacao` continua em `bronze_ipca.py`, que filtra as chaves por agregado e mês.
- **Delta foi assumido** como formato, seguindo as decisões de partida do plano. A escolha Delta × Iceberg continua sendo do ADR 0004.
- **A escrita no PostgreSQL e o `.json.gz` continuam**, como o plano pede para a E2. Saem na E3.
- **Fora desta entrega (E3):** `load_ipca.py` e `bronze.ipca_observacao` no DuckDB, `ipca_metadados`, download do 1737 em uma requisição, renomear `ingest.py`, módulo Dagster próprio e os modelos dbt.
