# Arquitetura Medallion

Organização progressiva do dado: cada camada só lê da anterior, e a crua nunca é alterada. A regra vale para **todas** as fontes do repositório, do IPCA às commodities, mesmo quando o destino final e o número de camadas materializadas mudam.

## O que cada camada significa aqui

| Camada | Papel | Como aparece neste repositório |
|---|---|---|
| **Raw** | Resposta da origem exatamente como veio, comprimida e nunca reescrita | Um `.json.gz` por requisição em `data/raw/<fonte>/` |
| **Bronze** | Primeira materialização controlada, já estruturada mas ainda por fonte | Parquet em `data/parquet/` nas fontes analíticas; tabela temporária `carga` dentro da transação no IPCA; **em memória** (DataFrame do Pandas) nas séries do Banco Central |
| **Silver** | Dado tipado, sem ausências, sem duplicata, com chaves resolvidas | Tabelas do Postgres (IPCA/INPC) e tabelas do DuckDB único (demais fontes) |
| **Gold** | Recorte pronto para consumo — modelo ou tela — já cruzando o que interessa | Views do DuckDB (`vw_features_*`, `vw_pib_*`); no IPCA ainda planejada |

## A trilha de cada fonte

| Fonte | Raw | Bronze | Silver | Gold |
|---|---|---|---|---|
| [IPCA/INPC (SIDRA)](../fontes/sidra.md) | `data/raw/ipca-inpc/{agregado}-{AAAAMM}.json.gz` | Tabela temporária `carga`, viva só na transação do mês | Postgres: `observacao`, `classificacao`, `classificacao_versao`, `localidade`, `variavel`, `fonte_agregado` | View por (subitem, localidade, mês) — planejada |
| [Commodities e Energia](../fontes/commodities.md) | `data/raw/commodities_raw/` | `data/parquet/*.parquet` | DuckDB: `commodity`, `commodity_cotacao` | `vw_features_daily`, `vw_features_monthly` (PIVOT) |
| [Dólar Comercial](../fontes/dolar.md) | `data/raw/bcb/dolar_*.json.gz` | Em memória (deduplicação + `ffill`) | DuckDB: `dolar_cotacao` | Composta no `join` diário com as demais séries macro |
| [Taxa SELIC](../fontes/selic.md) | `data/raw/bcb/selic_*.json.gz` | Em memória (`ffill` sobre o calendário civil) | DuckDB: `selic_taxa` | Composta no `join` diário com as demais séries macro |
| [PIB e Setores (SIDRA 1846)](../fontes/pib.md) | `data/raw/pib_raw/` (um JSON gzip por ano) | `data/parquet/pib/` | DuckDB: `pib_setor`, `pib_valor` | `vw_pib_setor_trimestral`, `vw_pib_nucleo`, `vw_features_pib_trimestral` |
| [PIB da China](../fontes/pib_china.md) | `data/raw/pib_china/` | `data/parquet/pib_china/` | DuckDB: `pib_china` | Consumida direto da silver |

!!! note "Por que a bronze não é sempre persistida"
    A raw já guarda a origem intacta e reprocessável, então a bronze só se materializa quando alguém a lê. No IPCA, uma bronze persistida duplicaria ~4,7 mi linhas em texto sem nenhuma consulta que a leia. Nas fontes analíticas, o Parquet **é** a bronze e se paga: é o formato que o DuckDB lê direto e que permite recarregar o banco sem chamar a API. Nas séries do Banco Central o payload é pequeno o bastante para a transformação inteira caber em memória, e gravar um Parquet intermediário só criaria um terceiro arquivo a versionar.

## Dois destinos de silver, um por natureza de dado

- **Postgres** guarda a referência do IPCA/INPC e o transacional do lojista: dado normalizado, com FKs e restrições, gravado por migrations em `migrations/`.
- **DuckDB único** (`data/duckdb/inflatrack.duckdb`) guarda as séries analíticas. Um arquivo só, e não um por fonte, porque a pergunta do projeto cruza fontes — cruzar dentro de um arquivo é um `JOIN`, entre arquivos exigiria `ATTACH` em toda sessão. A decisão está no [ADR 0002](../adr/0002-duckdb-unico.md), e os esquemas em `scripts/setup_duckdb*.sql`.

## O que cada passagem faz

**Raw → Bronze** — é onde mora a limpeza específica de cada origem:

- **Marcadores de ausência:** o SIDRA usa `...`, `..`, `-` e `X`, e a Alpha Vantage usa `.`; todos são descartados, sem apagar valores negativos, que são deflação.
- **Tipagem:** valor para numérico e período para data, cada origem com seu formato (`AAAAMM` no SIDRA, `DD/MM/YYYY` no SGS, `MM-DD-YYYY` no Olinda, ISO no resto).
- **Deduplicação:** quando a origem devolve mais de um registro para a mesma data, fica o mais recente (no Olinda, o maior `dataHoraCotacao`).
- **Calendário civil:** nas séries diárias do Banco Central, `ffill()` estica a última observação útil sobre fins de semana e feriados, e a coluna `observado` distingue publicação real de valor preenchido ([ADR 0003](../adr/0003-bcb-macro.md)).

**Bronze → Silver** — carga idempotente, sempre reexecutável: `UPSERT` por chave natural de data (`ON CONFLICT DO UPDATE`) no DuckDB, índice único `observacao_versao_uk` no Postgres. Rodar a mesma janela cem vezes converge para o mesmo estado.

**Silver → Gold** — cruzamento e recorte: transposição para formato largo (`PIVOT`) nas séries que alimentam o modelo, resolução de vigência de nome e escolha entre variável publicada e derivada no IPCA, razões e pesos setoriais no PIB.

## Qualidade

- `just verificar-carga`: linhas, meses, localidades e categorias por fonte, contra o volume medido; lista meses faltando no meio da série (IPCA/INPC).
- Restrições do banco na silver: FKs para cesta, localidade e variável no Postgres; PKs de data e FK `pib_valor → pib_setor` no DuckDB; `mes_referencia` sempre no dia 1.
- Falha explícita em vez de sucesso falso: payload inesperado, resposta vazia, data inválida ou ausência de valor anterior para preencher o início da janela encerram a carga com código diferente de zero.
- `just check` (formatação, lint e testes) cobre clientes HTTP, transformações e a idempotência do `UPSERT`.
