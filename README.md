# InflaTrack

Plataforma de dados que responde ao pequeno e médio lojista **quanto a inflação
do setor dele subiu e qual reajuste ele precisa aplicar para não perder margem**.

Projeto Integrado da disciplina **Banco de Dados 2** — Engenharia de Software,
FCTE/UnB. Squad Tio IPCA.

## Pergunta de gestão

> Dado o setor, a praça e o período, qual foi a inflação acumulada dos produtos
> que este lojista vende — e qual o reajuste mínimo para preservar a margem?

Cinco perguntas derivadas, com o modelo em que cada uma fica fácil, estão em
`docs/carga.md`.

## Subir do zero

Requisitos: Docker Compose v2, [`uv`](https://docs.astral.sh/uv/) e
[`just`](https://just.systems).

```bash
git clone https://github.com/Bappoz/inflatrack.git && cd inflatrack
cp .env.example .env
just reset          # sobe o Postgres e aplica migrations/0001..0003 em ordem
just seed-amostra   # 3 meses do IPCA — confere que a ingestão funciona
```

Para a série inteira (jul/2006 a jul/2026, ~4,7 milhões de linhas, ~2,2 GB
baixados, dezenas de minutos):

```bash
just seed
just verificar-carga
```

`just --list` mostra todas as receitas. **O `justfile` é a fonte canônica dos
comandos** — não rode o comando cru.

## Fontes

Todas do SIDRA/IBGE, via `apisidra.ibge.gov.br`. Números medidos em 2026-09-08.

| Agregado | Índice | Período | Linhas com valor | Observação |
|---|---|---|---|---|
| [2938](https://sidra.ibge.gov.br/Tabela/2938) | IPCA | jul/2006 – dez/2011 | ~798 mil | **Não tem** acumulada em 12 meses; só 12 localidades |
| [1419](https://sidra.ibge.gov.br/Tabela/1419) | IPCA | jan/2012 – dez/2019 | ~2,19 mi | 464 categorias (POF 2008-2009) |
| [7060](https://sidra.ibge.gov.br/Tabela/7060) | IPCA | jan/2020 – | ~1,71 mi | 457 categorias (POF 2017-2018) |
| [7063](https://sidra.ibge.gov.br/Tabela/7063) | INPC | jan/2020 – | ~1,7 mi | Famílias de 1 a 5 salários mínimos |
| [1737](https://sidra.ibge.gov.br/Tabela/1737) | IPCA | dez/1979 – | 560 pontos | Número-índice (base dez/1993 = 100), só Brasil e índice geral |

Três armadilhas que a ingestão trata e que não são óbvias:

1. **A cesta muda.** Entre 2006 e 2026, 43 subitens mudaram de nome mantendo o
   mesmo código (`1111004` "Leite pasteurizado" → "Leite longa vida"), 111
   saíram e 103 entraram. Por isso o nome vive em `classificacao_versao` com
   vigência, e não colado no código.
2. **`-` é ambíguo.** Sozinho é marcador de ausente; `-0.67` é deflação de
   verdade. Filtrar por prefixo apagaria todo mês de deflação sem erro.
3. **A API tem teto de 50.000 valores por requisição.** Um mês do 7060 são
   31.076 e passa; dois são 62.152 e devolvem HTTP 400. A paginação mensal não
   é escolha, é imposição da origem.

## Estrutura

| Caminho | Papel |
|---|---|
| `migrations/` | Esquema físico, aplicado em ordem na primeira subida do container |
| `src/inflatrack/sidra.py` | Cliente da API do SIDRA (formato compacto `/f/c/h/n`) |
| `src/inflatrack/ingest.py` | CLI de carga: crua em `data/raw/`, depois `COPY` para o banco |
| `sql/` | Consultas de verificação de carga |
| `docs/adr/` | Decisões de arquitetura, formato Nygard |
| `docs/carga.md` | Caracterização da carga de trabalho (passo 1 do Método de Decisão) |
| `docs/diario/` | Diário de bordo semanal da Squad |

## Licença

Código sob MIT. Os dados são do IBGE e mantêm os termos de uso da origem.
