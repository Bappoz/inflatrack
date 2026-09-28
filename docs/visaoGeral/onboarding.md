# Onboarding

## Pré-Requisitos

- **Docker Compose v2** — só para o Postgres (IPCA/INPC e transacional). As fontes analíticas rodam sem ele.
- **Python 3.12+** ou [uv](https://docs.astral.sh/uv/)
- [just](https://just.systems)
- Uma chave gratuita da [Alpha Vantage](https://www.alphavantage.co/support/#api-key), só se for carregar commodities.

## Variáveis de ambiente

O `justfile` carrega o `.env` da raiz automaticamente (`set dotenv-load`). Ele não é versionado — crie o seu:

| Variável | Para que serve | Padrão |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Credenciais do Postgres, usadas pelo Compose e pela ingestão do SIDRA | `inflatrack` |
| `POSTGRES_HOST`, `POSTGRES_PORT` | Endereço do banco visto pelos scripts Python | `localhost`, `5432` |
| `ALPHAVANTAGE_API_KEY` | Autentica a coleta de commodities e energia | _(sem padrão; a carga falha sem ela)_ |

Sem `.env`, o Postgres sobe com os padrões acima e tudo funciona, exceto a carga de commodities.

## Execução rápida

```bash
git clone https://github.com/Bappoz/inflatrack.git && cd inflatrack
just reset          # sobe o Postgres e aplica migrations/0001..0003 em ordem
just seed-amostra   # 3 meses do IPCA — confere que a ingestão funciona
```

## Carregando as fontes

Cada fonte tem sua receita e pode ser carregada isoladamente. As que vão para o DuckDB **não** precisam do Postgres no ar.

| Fonte | Comando | Destino | Custo |
|---|---|---|---|
| [IPCA/INPC](../fontes/sidra.md) | `just seed` | Postgres | ~2,2 GB, dezenas de minutos |
| [Dólar](../fontes/dolar.md) | `just seed-dolar` | DuckDB | 1 requisição, segundos |
| [Selic](../fontes/selic.md) | `just seed-selic` | DuckDB | 1 requisição, segundos |
| [Commodities](../fontes/commodities.md) | `just seed-commodities` | DuckDB | 9 requisições, ~2 min (cota diária de 25) |
| Dólar + Selic + Commodities | `just seed-macro` | DuckDB | Em sequência: o DuckDB aceita um escritor por vez |
| [PIB e Setores](../fontes/pib.md) | `just pib` | DuckDB | ~10 s, ~400 KB |
| [PIB da China](../fontes/pib_china.md) | `just pib-china` | DuckDB | Segundos |

Depois da carga histórica do IPCA, confira o volume:

```bash
just verificar-carga
```

As receitas `pib` e `pib-china` fazem ingestão e carga em dois passos (`*-ingest` e `*-load`), que também podem ser chamados separadamente.

## Onde o dado cai

| Caminho | O que é |
|---|---|
| `data/raw/<fonte>/` | Resposta crua das APIs em JSON gzip, nunca reescrita |
| `data/parquet/` | Camada intermediária das fontes analíticas |
| `data/duckdb/inflatrack.duckdb` | Banco analítico único: séries macro, commodities e PIB |
| Postgres (via Docker) | IPCA/INPC e o lado transacional do lojista |

O papel de cada camada está em [Arquitetura Medallion](../arquitetura/arquiteturaMedallion.md).

## Trabalhando no repositório

```bash
just check        # formatação, lint e testes — o gate antes de dizer "pronto"
just docs         # documentação com live-reload em http://localhost:8000
just docs-build   # compila validando links (--strict)
just psql         # abre o psql no banco do Compose
just db-ui        # Adminer em http://localhost:8080
```

!!! tip "Comandos Canônicos"
    O `justfile` é a fonte canônica dos comandos do projeto. Execute `just --list` para visualizar todas as receitas disponíveis.
