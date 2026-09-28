# PIB da Rússia (World Bank) — Dicionário de Dados

## Contexto

Tabela que recebe os dois indicadores anuais do PIB russo publicados pelo Banco Mundial (`NY.GDP.MKTP.KD.ZG` e `NY.GDP.MKTP.CD`, país `RUS`). Fica localizada em `data/duckdb/inflatrack.duckdb`, o mesmo banco analítico único das commodities, séries do Banco Central e do PIB da China/EUA — ver [ADR 0002](../adr/0002-duckdb-unico.md).

Três decisões moldam o esquema:

- **Uma tabela larga, sem dimensão.** Os dois indicadores viram duas colunas da mesma linha, sem necessidade de dimensão de indicador.
- **`ano` é a chave, não uma data.** A série é anual e o Banco Mundial a publica como ano civil (`date: "2024"`).
- **UPSERT por ano, com marca de carga.** `atualizado_em` registra quando a linha foi gravada pela última vez para registrar revisões do Banco Mundial.

!!! info "Sem dado pessoal"
    Agregado macroeconômico global, publicado por organismo multilateral. Nenhuma pessoa é identificável.

!!! warning "As duas colunas não são comparáveis entre si"
    `crescimento_pib_pct` é real (volume, descontada a inflação) e `pib_usd` é nominal em dólar corrente. Para taxa de crescimento, use a coluna de crescimento; nunca a derive do nível.

## Modelo Conceitual

```mermaid
erDiagram
    pib_russia {
        SMALLINT ano PK
        DOUBLE crescimento_pib_pct
        DOUBLE pib_usd
        TIMESTAMP atualizado_em
    }
```

Tabela única. Sem dimensão de localidade (só a Rússia) e sem dimensão de tempo (o ano é a própria chave).

## Entidades

### pib_russia

Uma linha por ano civil. O histórico do Banco Mundial para a Rússia inicia por volta de 1989/1990.

| Campo | Tipo | Descrição |
|---|---|---|
| `ano` | SMALLINT (PK) | Ano civil de referência, do campo `date` da API |
| `crescimento_pib_pct` | DOUBLE | Crescimento **real** do PIB no ano, em % (indicador `NY.GDP.MKTP.KD.ZG`). Nulo quando a API devolve `value: null` |
| `pib_usd` | DOUBLE | PIB **nominal** em dólares correntes (indicador `NY.GDP.MKTP.CD`). Valor absoluto (ordem de grandeza de 10¹² USD). Nulo quando a API devolve `value: null` |
| `atualizado_em` | TIMESTAMP | Quando a linha foi gravada ou atualizada pela última vez (`DEFAULT current_timestamp`) |

Chave primária `ano`.

!!! danger "`NULL` indica ausência de dado publicado"
    O ano mais recente pode retornar `value: null` na API. Preserva-se o nulo no banco e recomenda-se o uso de `WHERE crescimento_pib_pct IS NOT NULL` em cálculos agregados.

## Views

Nenhuma. O cruzamento com as demais séries é feito na própria consulta por `year(data_referencia) = ano`.

## Camadas anteriores

| Camada | Caminho | Formato |
|---|---|---|
| Bruta | `data/raw/pib_russia/NY.GDP.MKTP.KD.ZG.json.gz` e `.../NY.GDP.MKTP.CD.json.gz` | Resposta da API em gzip |
| Transformada | `data/parquet/pib_russia/pib_russia.parquet` | Parquet único |

## Exemplos de Uso

```sql
-- PIB da Rússia x Preço Médio do Petróleo Brent
select r.ano,
       r.crescimento_pib_pct,
       avg(c.preco) filter (c.symbol = 'BRENT') as brent_medio_usd
from pib_russia r
join commodity_cotacao c on year(c.data_referencia) = r.ano
where r.ano >= 2000
group by r.ano, r.crescimento_pib_pct
order by r.ano desc;
```

## Referências

- [Crescimento do PIB (NY.GDP.MKTP.KD.ZG) — Rússia](https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG?locations=RU)
- [PIB nominal em USD (NY.GDP.MKTP.CD) — Rússia](https://data.worldbank.org/indicator/NY.GDP.MKTP.CD?locations=RU)
- Caracterização da origem: [PIB da Rússia (World Bank)](../fontes/pib_russia.md)
- Decisão do banco: [ADR 0002 — DuckDB único](../adr/0002-duckdb-unico.md)
