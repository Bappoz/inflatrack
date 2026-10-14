# Evidência E2 — PIB e setores (SIDRA 1846)

Executado em **2026-10-13** contra a API do SIDRA (`deltalake` 1.6.6, `duckdb` 1.5.5). Não usa o PostgreSQL.

!!! info "Onde está o código"
    [`bronze.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/bronze.py) é o helper comum (contrato 4.1). [`bronze_pib.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/bronze_pib.py) tem a transformação, as checagens e a importação, e é chamado por [`ingest_pib.py`](https://github.com/Bappoz/inflatrack/blob/main/src/inflatrack/ingest_pib.py). Testes em `tests/test_pib.py` e `tests/test_bronze.py`, com respostas reais em `tests/fixtures/pib/`.

## Situação das tarefas da E2

| Tarefa | Situação |
|---|---|
| Helper comum e `pib_resposta` + `pib_valor` em Delta, com código e nome do setor e `valor_bruto` | Feita |
| Importar `data/raw/pib_raw/` | Feita: 31 arquivos |
| Demonstração de reexecução | Feita |
| Política de dado atrasado | Feita |
| Checagens: 23 categorias por trimestre; 2.806 linhas em 1996T1–2026T2 | Feitas |
| Diário de bordo das Semanas 7 a 10 | **Pendente** (texto pessoal) |

Também ficou pronto um item da E3: o ingestor só aceita resposta vazia no ano corrente e falha num ano passado vazio.

## Como reproduzir

```bash
just bronze-pib-importar   # Raw antigo -> Delta, sem chamar a API de valores
just bronze-pib            # 1996 até hoje: 32 requisições, ~10 s
just bronze-pib            # de novo: nada novo
just bronze-pib-checar
```

## O que é gravado

| Tabela | Uma linha por | Volume |
|---|---|---|
| `pib_resposta` | Resposta diferente: uma por ano, mais os metadados do agregado | 63 (32 importadas + 31 baixadas) |
| `pib_valor` | Valor da resposta: setor × trimestre, inclusive marcador | 2.806 |

A resposta de metadados também é guardada, porque é dela que sai o nome do setor. `grupo`, `nucleo`, `ano` e `trimestre` não são mais calculados na Bronze: ficam para o dbt. O Raw e o Parquet por ano continuam até a E3.

## Demonstração de reexecução

```text
importar (pasta vazia)   31 respostas novas, 2806 de 2806 linhas novas
importar de novo         0 respostas novas, 0 de 2806 linhas novas
ingestão 1 (API)         31 respostas novas de 31; pib_valor com 0 de 2806 linhas novas
ingestão 2 (API)         0 respostas novas de 31; pib_valor com 0 de 2806 linhas novas
```

Depois das quatro execuções, `pib_valor` continua na versão 0 do Delta, com 2.806 linhas.

A ingestão 1 grava 31 respostas novas sem acrescentar nenhuma linha. O corpo importado é o JSON que o ingestor antigo regravou, e não o texto original da API, então o hash é outro. Os valores são os mesmos e por isso nenhuma linha entra. A ingestão pelo Dagster (`pib_job`) também terminou com sucesso e sem nada novo.

**Semântica:** pelo menos uma vez na leitura, com escrita idempotente (efetivamente uma vez nas tabelas).

## Política de dado atrasado

| Situação | O que o pipeline faz |
|---|---|
| Trimestre ainda não divulgado | O SIDRA devolve `[]`. No ano corrente o ano é pulado; num ano passado a execução falha |
| Revisão de trimestre já divulgado | `pib_valor` só acrescenta, com o valor na chave: a revisão vira linha nova e a anterior fica |
| Janela relida | **A série inteira** a cada execução |

!!! warning "Ajuste ao plano"
    O plano propunha reler só o ano corrente e o anterior. Reler tudo custa 32 requisições e ~10 s, e o hash evita guardar o que não mudou. Assim também é vista a revisão anual das Contas Nacionais, que pode alcançar anos mais antigos.

O agendamento (`pib_job`) roda todo dia em março, junho, setembro e dezembro, os meses de divulgação.

## Checagens

Rodam antes de qualquer escrita. Ano reprovado não entra em nenhuma tabela, nem no Raw.

| Checagem | Falha quando |
|---|---|
| Esquema | Campo a mais ou a menos que `NC`, `MC`, `V`, `D1C`, `D2C`, `D3C`, `D4C` |
| Valor | `V` não é número nem marcador |
| Recorte | Nível diferente de Brasil, variável diferente de 585 ou unidade diferente de 1550 |
| Setores | Trimestre sem exatamente 23 setores, ou com setor repetido |
| Trimestres | Buraco na sequência, ou ano anterior ao passado sem os 4 trimestres |

`just bronze-pib-checar` sobre a tabela gravada:

```text
primeiro_trimestre=1996-01-01 ultimo_trimestre=2026-04-01 trimestres=122 trimestres_faltando=0
linhas=2806 valores_distintos=2806 trimestres_fora_de_23_setores=0 linhas_de_revisao=0
linhas_sem_valor=0 respostas=63
```

Nenhum marcador aparece no histórico do 1846: as 2.806 linhas têm valor.

## Medições para o ADR 0004

| Onde | Tamanho |
|---|---|
| `data/raw/pib_raw/` (31 `.json.gz`) | 22 KB |
| `pib_resposta` (63 respostas, snappy) | 449 KB |
| `pib_valor` (1 arquivo) | 52 KB |

`pib_valor` é gravada num único commit por execução, e não por ano, e não tem partição: são 2.806 linhas. `pib_resposta` cria um arquivo por resposta nova; com o hash, isso só acontece quando o IBGE publica algo diferente.

**Compressão.** Cada tabela regravada num único Parquet por codec; leitura de todas as linhas pelo DuckDB, melhor de 3.

| Tabela | snappy | zstd | gzip |
|---|---|---|---|
| `pib_resposta` (63) | 93 KB, 3 ms | 54 KB, 3 ms | 53 KB, 3 ms |
| `pib_valor` (2.806) | 51 KB, 28 ms | 37 KB, 27 ms | 39 KB, 29 ms |

O zstd ocupa ~40% menos que o snappy na tabela de respostas com o mesmo tempo de leitura. As tabelas estão em snappy, o padrão do `deltalake`.

**Respostas que o hash evitou.** Medido só num dia (2026-10-13), e não numa semana: na reexecução, 31 de 31 respostas eram iguais às já guardadas. A medição de uma semana continua pendente.
