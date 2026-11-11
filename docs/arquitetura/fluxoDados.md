# Fluxo de Dados

Do dado de origem ao consumo pelo lojista. As camadas estão em [Arquitetura Medallion](arquiteturaMedallion.md), as peças em [Componentes](componentes.md) e o detalhe de cada etapa em [Contrato das Etapas](../pipeline/contratoEtapas.md).

<div class="diagrama">
--8<-- "docs/assets/diagramas/fluxo-dados.svg"
</div>

## O percurso, etapa por etapa

1. **Extração** — o cliente de origem (`sidra.py`, `alphavantage.py`, `dolar_olinda.py`, `selic_sgs.py`, `pib.py`, `dieese.py`, `inmet.py`) fala com uma origem só e devolve o payload sem interpretá-lo.
2. **Resposta original** — o ingestor guarda a resposta antes de qualquer transformação, com o SHA-256 do corpo, na tabela `<fonte>_resposta` do Delta (o formato antigo, `.gz` em `data/raw/<fonte>/`, só é lido pelos comandos `importar`).
3. **Bronze** — o mesmo ingestor parseia e tipa, e grava tabelas Delta Lake sobre Parquet em `data/parquet/<fonte>/`, com data de ingestão e procedência em cada linha. O loader espelha o Delta em `bronze.*` no DuckDB.
4. **Silver** — os modelos de staging e intermediários do dbt fazem limpeza, deduplicação e resolução de chaves, e agregam cada fonte ao grão mensal. Dólar e Selic entram só com os dias úteis publicados (ver [ADR 0003](../adr/0003-bcb-macro.md)).
5. **Gold** — os modelos de *marts* materializam no DuckDB o fato do IPCA, a dimensão de variação lenta da cesta (`dim_cesta_ipca_scd2`), o preço do lojista (`dim_produto_preco_scd2`), câmbio e juros, salário mínimo e PIB internacional. A matriz de treino é da E4.
6. **Consumo** — o ativo `serie_postgres` copia a Gold para o schema `serie` do PostgreSQL e o Metabase responde às cinco perguntas de gestão a partir dali. Notebooks e modelo preditivo são da E4.

Em paralelo, o **PostgreSQL** atende o lado transacional: cadastro de lojista e produto, e a aplicação de reajuste, que é a única escrita que exige transação. É de lá que vem a FK `produto.codigo_subitem_ipca`, a ponte entre o catálogo do lojista e a cesta do IBGE.

## Cadência

| Fonte | Chega | Partição | Gatilho hoje |
|---|---|---|---|
| SIDRA (7060, 7063, 1737) | mensal, dias 9 a 12 | mensal | manual (`uv run python -m inflatrack.bronze.ipca coletar`) |
| SIDRA (2938, 1419) | nunca mais (séries encerradas) | — | só na carga histórica (`just seed`) |
| SIDRA 1846 (PIB e setores) | trimestral | trimestral | manual (`just pib`) |
| BCB (Olinda e SGS) | diária (dias úteis) | diária | manual (`just seed-macro`) |
| Alpha Vantage | diária / mensal | diária | manual (`just seed-macro`) |
| Banco Mundial (PIB da China) | anual | anual | manual (`just pib-china`) |
| DIEESE (salário mínimo) | mensal | mensal | manual (`just salario-minimo`) |
| INMET (clima e estações) | diária (pacote anual do BDMEP, republicado ~1×/mês) | diária | `clima_job` 1×/dia às 7h (`just clima` fora do Dagster) |

O gatilho manual continua valendo, mas cada linha acima também é um ativo do Dagster, com retry, partições (IPCA, INPC e PIB) e backfill da janela histórica. Os agendamentos existem e nascem desligados; ver [Orquestração](../pipeline/orquestracao.md).

!!! note "Escritor único no DuckDB"
    O DuckDB aceita um escritor por arquivo, por vez. Isso vale para os três processos que tocam o banco: a carga, o `dbt build` e o painel. O Dagster serializa as escritas, e o Metabase lê a cópia da Gold em `serie` no PostgreSQL em vez do arquivo em construção.
