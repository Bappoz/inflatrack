# Fluxo de Dados

Do dado de origem ao consumo planejado pelo lojista. As camadas estão em [Arquitetura Medallion](arquiteturaMedallion.md), as peças em [Componentes](componentes.md) e o detalhe de cada etapa em [Contrato das Etapas](../pipeline/contratoEtapas.md).

<div class="diagrama">
--8<-- "docs/assets/diagramas/fluxo-dados.svg"
</div>

## O percurso, etapa por etapa

1. **Extração** — o cliente de origem (`sidra.py`, `alphavantage.py`, `dolar_olinda.py`, `selic_sgs.py`, `pib.py`, `dieese.py`, `inmet.py`) fala com uma origem só e devolve o payload sem interpretá-lo.
2. **Raw** — o ingestor grava a resposta comprimida em `data/raw/<fonte>/`, antes de qualquer transformação.
3. **Bronze** — o mesmo ingestor parseia e tipa, e materializa tabelas em `data/parquet/<fonte>/`: Delta Lake sobre Parquet nas fontes migradas e Parquet simples nos fluxos legados, com data de ingestão e procedência em cada linha.
4. **Silver (alvo)** — quando o projeto dbt estiver criado, os modelos de staging farão limpeza, deduplicação, calendário civil e resolução de chaves. Hoje os loaders legados do BCB preenchem o calendário diretamente; a Bronze Delta mantém as observações originais.
5. **Gold** — os modelos de *marts* materializam no DuckDB o fato do IPCA, a dimensão de variação lenta da cesta, as features macro e a matriz de treino.
6. **Consumo** — notebooks treinam e comparam modelos, com MLflow registrando cada execução; o painel Streamlit responde às cinco perguntas de gestão.

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
| INMET (clima e estações) | diária | diária | manual (`just clima`) |

O gatilho manual é transitório: com o Dagster, cada linha acima vira um ativo particionado, com retry por partição e backfill da janela histórica.

!!! note "Escritor único no DuckDB"
    O DuckDB aceita um escritor por arquivo, por vez. Isso vale para os três processos que tocam o banco: a carga, o `dbt build` e o painel. O Dagster serializa as escritas, e o Streamlit lê uma cópia publicada da Gold em vez do arquivo em construção.
