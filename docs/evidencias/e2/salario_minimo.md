# Evidência E2 — Salário Mínimo (DIEESE)

O que a fonte `salario_minimo` entrega na Entrega 2, com o comando que produziu cada número. Tudo nesta página foi executado em **2026-10-12**, contra a página pública da Pesquisa Nacional da Cesta Básica de Alimentos do DIEESE (`deltalake` 1.6.6, `duckdb` 1.5.5, `pyarrow` 25.0.1).

!!! info "Onde está o código"
    [`src/inflatrack/bronze_salario_minimo.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/bronze_salario_minimo.py) (transformação, checagens, gravação em Delta e importação), integrado a [`ingest_salario_minimo.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/ingest_salario_minimo.py). Testes unitários completos em `tests/test_salario_minimo.py`, com fixture real da página em `tests/fixtures/salario_minimo/salario_minimo.html`. Esquema das tabelas Delta no [Dicionário de Dados](../../dicionario/salario_minimo.md#bronze-em-delta).

## Situação das tarefas da E2

Itens da seção 3.7 das tasks que o grupo separou.

| Tarefa | Situação | Evidência |
|---|---|---|
| `salario_minimo_resposta` (HTML inteiro) e `salario_minimo_mes` em Delta, com todas as linhas e sem coluna calculada | Feita | [Transformação](#transformacao) |
| Importar os `.html.gz` de `data/raw/dieese/` para `salario_minimo_resposta` | Feita | [Importação do Raw antigo](#importacao-do-raw-antigo) |
| Demonstração de reexecução e política | Feita | [Reexecução](#demonstracao-de-reexecucao) e [Política](#politica-de-dado-atrasado) |
| Checagens de esquema e volume: `ano_mes` único, série desde 1994-07 | Feitas | [Checagens](#checagens-de-esquema-e-volume) |
| Diário de bordo das Semanas 7 a 10 | Feita | Registrado na seção da Squad |

## Como reproduzir

```bash
just bronze-salario-minimo            # Baixa o HTML, grava Raw, Bronze Delta e Parquet
just bronze-salario-minimo            # Reexecução: resposta já guardada, 0 meses novos
just bronze-salario-minimo-checar     # Valida continuidade, sem buracos e volume >= 387
just bronze-salario-minimo-importar   # Importa .html.gz de data/raw/dieese/ sem chamar a web
just test                             # 78 testes automatizados passando
```

## Transformação

`transformar(html_conteudo)` analisa a tabela HTML e devolve **uma linha por mês**, na ordem cronológica de apuração. Nenhuma linha é descartada e a coluna calculada `multiplo_necessario_nominal` foi removida da camada Bronze, ficando como transformação para o dbt Silver (conforme a seção 2.2 do plano).

| Campo no HTML | Coluna Bronze | Conversão |
|---|---|---|
| Cabeçalho de ano `<tr class="subtitulo">` | `ano` | Inteiro (`smallint`) |
| 1ª coluna `<td>` (Mês) | `mes` | Inteiro de 1 a 12 |
| Ano e Mês compostos | `ano_mes` | Texto no padrão `YYYY-MM` |
| Primeiro dia do mês | `data_referencia` | Data canônica `YYYY-MM-01` |
| 2ª coluna `<td>` (Salário Nominal) | `salario_nominal` | `decimal(12,2)` (ex.: `1621.00`) |
| 3ª coluna `<td>` (Salário Necessário) | `salario_necessario` | `decimal(12,2)` (ex.: `7750.01`) |
| Metadado de auditoria | `_id_resposta` | Hash SHA-256 do corpo HTML |
| Metadado de auditoria | `_fonte` | `"salario_minimo"` |
| Metadado de auditoria | `_requisicao` | URL pública consultada no DIEESE |
| Metadado de auditoria | `_ingerido_em` | Timestamp UTC do download |

O que fica **fora** do ingestor e vai para o dbt:
- Derivação do múltiplo constitucional (`salario_necessario / salario_nominal`);
- Filtros de consistência fina e junção temporal com o IPCA por `data_referencia`.

## Carga histórica

Comando: execução direta da ingestão contra o portal do DIEESE.

| Tabela | Localização | Linhas | Período Coberto | Descrição |
|---|---|---|---|---|
| `salario_minimo_resposta` | `data/parquet/salario_minimo/resposta/` | 1 | — | HTML integral (53.195 bytes) |
| `salario_minimo_mes` | `data/parquet/salario_minimo/mes/` | 387 | jul/1994 a set/2026 | Histórico mensal ininterrupto |

A série histórica cobre **387 meses** sem nenhuma lacuna temporal desde o início do Plano Real (julho de 1994) até a última publicação disponível (setembro de 2026).

## Demonstração de reexecução

A execução consecutiva com o mesmo conteúdo não acrescenta linhas e é 100% idempotente:

```text
--- 1ª execução
2026-10-12 21:48:07 INFO Baixando página de salário mínimo do DIEESE...
2026-10-12 21:48:08 INFO HTTP Request: GET https://www.dieese.org.br/... "HTTP/1.1 200 OK"
2026-10-12 21:48:08 INFO HTML bruto salvo em data/raw/dieese/salario_minimo.html.gz (53195 bytes)
2026-10-12 21:48:08 INFO Bronze Delta: resposta nova, 387 de 387 meses novos em data/parquet/salario_minimo
2026-10-12 21:48:08 INFO Extraídos 387 registros mensais de salário mínimo

--- 2ª execução (reexecução imediata)
2026-10-12 21:48:49 INFO Baixando página de salário mínimo do DIEESE...
2026-10-12 21:48:49 INFO HTTP Request: GET https://www.dieese.org.br/... "HTTP/1.1 200 OK"
2026-10-12 21:48:49 INFO HTML bruto salvo em data/raw/dieese/salario_minimo.html.gz (53195 bytes)
2026-10-12 21:48:49 INFO Bronze Delta: resposta já guardada, 0 de 387 meses novos em data/parquet/salario_minimo
2026-10-12 21:48:49 INFO Extraídos 387 registros mensais de salário mínimo
```

**Por que é idempotente:**
1. A tabela de respostas calcula o SHA-256 do HTML recebido (`hash_corpo`). Se o hash já constar na tabela, nenhuma nova versão de resposta é adicionada.
2. A tabela de meses compara a chave composta `(ano_mes, salario_nominal, salario_necessario)`. Linhas já persistidas com os mesmos valores são ignoradas na gravação.
3. Se o DIEESE revisar um mês no futuro (por exemplo, retificação do salário necessário), o novo valor entra como **linha nova**, preservando o histórico auditável (*insert-only*).

## Checagens de esquema e volume

As checagens são executadas em memória antes de qualquer escrita no Delta. Respostas inconsistentes provocam `ChecagemError` e não poluem as tabelas analíticas.

| Checagem | Critério de Aceitação | Falha se |
|---|---|---|
| Esquema da tabela | `<table>` presente com linhas `<tr>` e colunas válidas | Não houver tabela ou linhas |
| Unicidade | Uma única linha por mês no payload | Houver repetição de `ano_mes` |
| Ponto de partida | Marco inicial em julho de 1994 (`1994-07-01`) | O primeiro registro for diferente |
| Continuidade temporal | Sequência de meses sem nenhum mês faltante | Houver buraco na sequência contínua |
| Volume de referência | Mínimo de 387 meses | O total for menor que o esperado |

Execução do comando de verificação:

```bash
just bronze-salario-minimo-checar
```

Saída:
```text
salario_minimo_mes linhas=387 primeiro_mes=1994-07-01 ultimo_mes=2026-09-01 versoes=0 status=OK
```

Todos os 387 meses passaram: nenhum faltando, nenhum duplicado e série contínua.

## Importação do Raw antigo

Para ambientes com arquivos `.html.gz` em `data/raw/dieese/`, o comando `just bronze-salario-minimo-importar` migra o conteúdo diretamente para o Delta:

```bash
just bronze-salario-minimo-importar
```

Saída:
```text
INFO Importação: 0 respostas novas, 0 meses novos, 0 falhas
```
Como a ingestão já havia sido executada, o importador reconheceu o hash e não duplicou registros.

## Política de dado atrasado

Texto da fonte `salario_minimo` para o ADR 0004 (seção 2.6 das tasks que o grupo separou).

| Situação | Comportamento da Origem | O que o pipeline faz |
|---|---|---|
| **Periodicidade da divulgação** | Mensal, tipicamente na 1ª quinzena do mês subsequente (sem dia fixo). | O agendamento monitora na primeira quinzena. Como a página traz a série inteira em uma única requisição HTTP, a cada execução o HTML integral é inspecionado. |
| **Revisão histórica pelo DIEESE** | O DIEESE ocasionalmente retifica estimativas do salário necessário de meses anteriores. | Como a chave analítica da Bronze inclui os valores monetários, a revisão vira uma **nova linha** na tabela Delta; a estimativa anterior continua preservada com seu carimbo temporal de ingestão. |
| **Reprocessamento manual** | — | Qualquer reexecução de `just bronze-salario-minimo` é segura e não duplica dados existentes. |

## Achados e limitações

- **Codificação de caracteres:** A página do DIEESE utiliza codificação `ISO-8859-1` (`latin1`). O cliente HTTP decodifica explicitamente o cabeçalho `Content-Type` para evitar corrupção de acentuação nos nomes dos meses (como `Março`).
- **Remoção de métricas calculadas na Bronze:** O pipeline anterior calculava `multiplo_necessario_nominal` no momento da extração. Conforme as regras da Bronze na E2, essa derivação foi suprimida e será implementada como modelo de staging no dbt Silver.
- **Transição suave para E3:** Durante a Entrega 2, o gerador de Parquet legado em `data/parquet/dieese/salario_minimo.parquet` continua sendo atualizado em paralelo para assegurar o funcionamento contínuo de `load_salario_minimo.py` no DuckDB até a migração definitiva para modelos dbt.
