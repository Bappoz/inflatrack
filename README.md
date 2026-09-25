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
just reset          # sobe o Postgres e aplica migrations/0001..0004 em ordem
just seed-amostra   # 3 meses do IPCA — confere que a ingestão funciona
just seed-pib-china # carrega o histórico do PIB da China (World Bank API)
```

Para a série inteira (jul/2006 a jul/2026, ~4,7 milhões de linhas, ~2,2 GB
baixados, dezenas de minutos):

```bash
just seed
just verificar-carga
```

`just --list` mostra todas as receitas. **O `justfile` é a fonte canônica dos
comandos** — não rode o comando cru.

## Visualização no Navegador

### 1. Interface Gráfica do Banco de Dados (Adminer)
Para visualizar as tabelas do PostgreSQL e as linhas salvas direto pelo navegador:
```bash
just db-ui
# Ou comando equivalente:
# docker rm -f adminer 2>/dev/null ; docker run -d --name adminer --network inflatrack_default -p 8080:8080 adminer
```
Acesse em: 👉 **[http://localhost:8080](http://localhost:8080)**

* **Sistema**: `PostgreSQL`
* **Servidor**: `inflatrack-db-1`
* **Usuário / Senha / Banco**: `inflatrack`

## Fontes

### Referência de Inflação Nacional (SIDRA/IBGE)

| Agregado | Índice | Período | Linhas com valor | Observação |
|---|---|---|---|---|
| [2938](https://sidra.ibge.gov.br/Tabela/2938) | IPCA | jul/2006 – dez/2011 | ~798 mil | **Não tem** acumulada em 12 meses; só 12 localidades |
| [1419](https://sidra.ibge.gov.br/Tabela/1419) | IPCA | jan/2012 – dez/2019 | ~2,19 mi | 464 categorias (POF 2008-2009) |
| [7060](https://sidra.ibge.gov.br/Tabela/7060) | IPCA | jan/2020 – | ~1,71 mi | 457 categorias (POF 2017-2018) |
| [7063](https://sidra.ibge.gov.br/Tabela/7063) | INPC | jan/2020 – | ~1,7 mi | Famílias de 1 a 5 salários mínimos |
| [1737](https://sidra.ibge.gov.br/Tabela/1737) | IPCA | dez/1979 – | 560 pontos | Número-índice (base dez/1993 = 100), só Brasil e índice geral |

### Variáveis Macroeconômicas e Externas

| Fonte | Indicador | Período | Frequência | Papel no Projeto |
|---|---|---|---|---|
| [Alpha Vantage](https://www.alphavantage.co/) | Commodities e Energia | Séries históricas | Diária / Mensal | Cotações de petróleo, gás natural e commodities agrícolas |
| [World Bank API](https://data.worldbank.org/country/china) | PIB da China | 1960 – 2025 | Anual / Trimestral | Indicador antecedente de demanda global por commodities |

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
| `migrations/` | Esquema físico (0001..0004), aplicado em ordem na primeira subida do container |
| `src/inflatrack/sidra.py` | Cliente da API do SIDRA (formato compacto `/f/c/h/n`) |
| `src/inflatrack/ingest.py` | CLI de carga do IPCA/INPC: crua em `data/raw/ipca-inpc/`, depois `COPY` para o banco |
| `src/inflatrack/ingest_pib_china.py` | Ingestão e carga do PIB da China (World Bank API) no PostgreSQL |
| `sql/` | Consultas de verificação de carga |
| `docs/adr/` | Decisões de arquitetura, formato Nygard |
| `docs/fontes/pib_china.md` | Caracterização completa da fonte do PIB da China |
| `mkdocs.yml` | Configuração da documentação (Material for MkDocs) e GitHub Pages |

## Documentação

A documentação interativa com busca, diagramas e detalhes arquiteturais está publicada via GitHub Pages em:
👉 **[https://bappoz.github.io/inflatrack/](https://bappoz.github.io/inflatrack/)**

## Licença

Código sob MIT. Os dados são do IBGE e mantêm os termos de uso da origem.
