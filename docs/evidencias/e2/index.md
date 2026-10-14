# Evidências da E2

Uma página por fonte, cada uma com o comando executado, a saída da reexecução e as checagens. Esta página junta a situação de todas.

## Situação por fonte

| Fonte | Bronze em Delta | Reexecução sem duplicar | Checagens | Página |
|---|---|---|---|---|
| IPCA/INPC (SIDRA) | Feita | Feita | Feitas | [ipca.md](ipca.md) |
| Commodities (Alpha Vantage) | Feita | Feita | Feitas | [commodities.md](commodities.md) |
| PIB e setores (SIDRA 1846) | Feita | Feita | Feitas | [pib.md](pib.md) |
| Dólar, Selic, PIB da China, Salário mínimo, Clima, Transacional (CDC) | Pendente | Pendente | Pendente | — |

## Reproduzir

```bash
cp .env.example .env   # e preencha ALPHAVANTAGE_API_KEY
uv sync
just e2                # Bronze de cada fonte, seguida das checagens
```

O `just e2` foi testado em 2026-10-13 numa cópia limpa dos arquivos do repositório, sem `data/` e sem `.venv`. Resultados:

- `just test` passou;
- o PIB foi carregado do zero, com a checagem aprovada;
- sem a chave, as commodities param antes de fazer qualquer requisição.

A versão com a chave não foi repetida na cópia limpa, para não passar da cota diária. O teste oficial a partir de um `git clone`, feito por outra pessoa, continua pendente.

## Convenções conferidas

Conferido em 2026-10-13 nas três fontes, pelo esquema das tabelas gravadas (PIB e commodities) e pelo código (IPCA, cujas tabelas não estavam nesta máquina):

| Convenção | IPCA | Commodities | PIB |
|---|---|---|---|
| Pasta | `data/parquet/ipca/` | `data/parquet/commodities/` | `data/parquet/pib/` |
| Tabela de respostas com as colunas do helper | Sim | Sim | Sim |
| Metadados `_id_resposta`, `_fonte`, `_requisicao`, `_ingerido_em` no fim da tabela extraída | Sim | Sim | Sim |
| `_fonte` igual ao id da fonte | `ipca` | `commodities` | `pib` |
| Módulo Dagster próprio | Não (em `ingestao.py`) | `assets/commodities.py` | `assets/pib.py` |

!!! warning "Parquet antigo na mesma pasta"
    Até a E3, o Parquet antigo continua junto da Bronze: `data/parquet/pib/1846-AAAA.parquet` fica ao lado de `resposta/` e `valor/`, e o das commodities fica na raiz de `data/parquet/`. As cargas antigas leem só o primeiro nível da pasta e por isso não misturam os dois.

## Modelo da evidência

Cada fonte cria `docs/evidencias/e2/<base>.md` com estas seções, nesta ordem, e acrescenta uma linha na tabela acima:

1. **Cabeçalho:** a data da execução, contra o que ela rodou e as versões das bibliotecas.
2. **Onde está o código:** os módulos, os testes e as fixtures.
3. **Situação das tarefas da E2:** uma linha por item da seção 3 das tasks que o grupo separou.
4. **Como reproduzir:** as receitas do `just`.
5. **O que é gravado:** as duas tabelas, o que é uma linha e o volume.
6. **Demonstração de reexecução:** a versão do Delta e a contagem de linhas antes e depois, e o log da segunda execução.
7. **Política de dado atrasado:** o texto da fonte para o ADR 0004.
8. **Checagens:** o que faz a execução falhar e a saída da checagem sobre a tabela gravada.
9. **Medições para o ADR 0004:** tamanho, codec e número de arquivos.
