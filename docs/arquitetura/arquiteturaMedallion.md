# Arquitetura Medallion

Organização progressiva do dado: cada camada só lê da anterior, e a crua nunca é alterada.

## Camadas no IPCA (SIDRA)

| Camada | Papel | Onde aparece | Status |
|---|---|---|---|
| **Raw** | Resposta da API exatamente como veio | `data/raw/ipca-inpc/{agregado}-{AAAAMM}.json.gz` | Implementado |
| **Bronze** | Primeira materialização controlada | Tabela temporária `carga`, que existe só dentro da transação de cada mês | Implementado (não persistida) |
| **Silver** | Dado tipado, sem ausências, sem duplicata, com chaves da cesta resolvidas | `observacao`, `classificacao`, `classificacao_versao`, `localidade`, `variavel`, `fonte_agregado` | Implementado |
| **Gold** | Recorte pronto para as telas: nome vigente, acumulado 12 m resolvido, junção com o produto | View materializada por (subitem, localidade, mês) | Planejado |

!!! note "Por que não há bronze persistida"
    A raw já guarda a origem intacta e reprocessável. Uma tabela bronze só duplicaria ~4,7 mi linhas em texto sem nenhuma consulta que a leia.

## O que cada passagem faz

- **Raw → Silver:** descarta os marcadores `...`, `..`, `-` e `X` (sem apagar negativos, que são deflação), converte o valor para `numeric`, o mês para `date` e o `D4C` para o código natural da cesta. A deduplicação vem do índice único `observacao_versao_uk`.
- **Silver → Gold:** resolve a vigência do nome, escolhe entre a variável 2265 e a acumulada derivada (o agregado 2938 não tem a 2265) e junta o produto do lojista.

## Qualidade

- `just verificar-carga`: linhas, meses, localidades e categorias por fonte, contra o volume medido; lista meses faltando no meio da série.
- Restrições do banco na silver: FKs para cesta, localidade e variável; `mes_referencia` sempre no dia 1.

Commodities seguem Raw (JSON gzip em `data/raw/commodities_raw/`) → Parquet (`data/parquet/`) → DuckDB (`data/duckdb/`) → views `PIVOT`; ver [Commodities e Energia](../fontes/commodities.md).
