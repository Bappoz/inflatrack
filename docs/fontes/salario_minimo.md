# Salário Mínimo Nominal e Necessário (DIEESE)

Este documento registra as características arquiteturais e de negócio para a fonte de dados da **Pesquisa Nacional da Cesta Básica de Alimentos — Salário Mínimo Nominal e Necessário**, conduzida e divulgada pelo Departamento Intersindical de Estatística e Estudos Socioeconômicos ([DIEESE](https://www.dieese.org.br/analisecestabasica/salarioMinimo.html)).

## Séries coletadas

As séries são obtidas por extração direta da página pública do DIEESE:

| Indicador | Descrição | Unidade | Frequência de acesso |
|---|---|---|---|
| `salario_minimo_nominal` | Valor do salário mínimo oficial vigente fixado por lei federal | R$ (BRL) | Mensal |
| `salario_minimo_necessario` | Estimativa do DIEESE para o sustento de uma família de quatro pessoas (CF/88, art. 7º, IV) | R$ (BRL) | Mensal |
| `multiplo_necessario_nominal` | Razão entre o salário mínimo necessário e o nominal vigente | Razão (vezes) | Mensal |

O DIEESE calcula mensalmente o **salário mínimo necessário** tomando como referência o custo da cesta básica mais cara entre as capitais pesquisadas pelo instituto (frequentemente São Paulo ou Florianópolis) e a determinação constitucional (art. 7º, inciso IV da Constituição Federal de 1988), que estabelece que o salário mínimo deve atender às necessidades vitais básicas de uma família com alimentação, habitação, vestuário, educação, saúde, higiene, transporte, lazer e previdência social.

---

## 1. Fonte de Origem

| Atributo | Resposta |
| :--- | :--- |
| **Nome da fonte** | Pesquisa Nacional da Cesta Básica de Alimentos — Salário mínimo nominal e necessário |
| **Tipo** *(usuário / sistema / interna / terceiro)* | Terceiro |
| **Quem ou o que gera** | DIEESE - Departamento Intersindical de Estatística e Estudos Socioeconômicos |
| **O que essa fonte contém** | Variação do salário mínimo com o tempo e qual deveria ser o valor real (série histórica mensal desde julho de 1994 do salário mínimo nominal vigente e do salário mínimo necessário apurado com base no custo de vida familiar). |
| **Formato em que chega** *(JSON, CSV, formulário, API...)* | Site (webscraping necessário a partir da tabela HTML em `salarioMinimo.html`) |
| **Volume estimado** *(por dia ou por mês)* | Um por mês (1 requisição HTTP mensal para atualização incremental; na carga histórica, 1 única requisição recupera toda a série histórica desde 1994 com ~380 meses / ~400 linhas). |
| **Frequência de chegada** *(tempo real / horária / diária / eventual)* | Mensal (publicado mensalmente após o fechamento da pesquisa da cesta básica das capitais). |
| **Vazão** *(alta / média / baixa)* | Baixa |
| **Pureza** *(alta / média / baixa)* | Alta (dados estatísticos consolidados pelo corpo técnico do DIEESE; requer apenas higienização padrão de strings como limpeza de prefixos monetários "R$" e conversão de pontuação numérica brasileira). |
| **Previsibilidade do formato** *(alta / média / baixa)* | Alta (tabela HTML estruturada com agrupamento por subtítulo de ano e colunas fixas: Período, Salário mínimo nominal e Salário mínimo necessário). |
| **Contém dado pessoal?** *(sim / não)* | Não |
| **Base legal LGPD** *(se contém dado pessoal)* | Não se aplica (dados macroeconômicos e estatísticos públicos sem identificação de pessoas físicas). |
| **Retenção** *(por quanto tempo guardar)* | 5 anos (mínimo de governança do projeto, preservando retenção permanente no banco analítico DuckDB para treino e backtesting de modelos históricos). |
| **O que quebra se essa fonte falhar** | Não será possível traçar um paralelo entre a variação do preço dos produtos e o salário mínimo da população. A ausência do indicador prejudica a modelagem de elasticidade de renda e o cálculo do repasse de custos suportável pelo consumidor final. |

---

## 2. Conjunto de Dados / Armazenamento

| Atributo | Resposta |
| :--- | :--- |
| **Conjunto de dados** | Série Histórica do Salário Mínimo Nominal e Necessário (Raw / Silver) |
| **Fonte de origem** *(nº da aba 1)* | DIEESE - Pesquisa Nacional da Cesta Básica de Alimentos |
| **Formato atual** | `.html.gz` / `.json.gz` (Raw em `data/raw/dieese/`), `.parquet` (Silver em `data/parquet/dieese/`) e tabela `salario_minimo` no DuckDB analítico compartilhado (`data/duckdb/inflatrack.duckdb`) |
| **Texto ou binário** | Binário (o raw comprimido em gzip, Parquet e base colunar DuckDB) |
| **Orientação** *(linha / coluna / não se aplica)* | Linha (tabela física com uma observação por mês) com armazenamento colunar otimizado no DuckDB e Parquet |
| **Tamanho estimado** *(em 1 ano)* | < 1 MB / ano (12 registros mensais por ano; o histórico completo de 30 anos ocupa poucos kilobytes) |
| **Como é lido** *(registro inteiro / poucas colunas / busca por chave)* | Busca por chave temporal (`ano_mes` ou `data_referencia`) e recortes temporais completos para junções analíticas (*joins*) com o IPCA/INPC e vendas do lojista |
| **Frequência de leitura** | Média a Alta (consultado em rotinas de análise de correlação entre reajuste de preços e perda de poder aquisitivo) |
| **Formato proposto** | Preservar o HTML original em `.html.gz` na camada raw, materializar Parquet na camada silver e carregar no DuckDB compartilhado. |
| **Justificativa da escolha** | O DuckDB analítico único segue o [ADR 0002](../adr/0002-duckdb-unico.md), permitindo `JOIN` temporal direto por `ano_mes` com a série do IPCA/INPC (SIDRA), PIB e cotações de commodities sem duplicar infraestrutura. |
| **Ganho esperado** *(se houver troca)* | Eliminação de requisições de raspagem repetitivas, latência sub-milissegundo em consultas analíticas e suporte nativo ao ecossistema Python (Pandas/Polars). |

---

## 3. Carga de trabalho

### Taxa de escrita

- **Carga histórica:** Evento único, 1 requisição HTTP GET para a página `salarioMinimo.html`, que recupera a série temporal completa de 1994 até a data mais recente (~380 meses observados).
- **Regime:** 1 registro novo publicado por mês (~12 linhas por ano).
- **Escrita real vs. custo de coleta:** O raspador coleta o documento HTML consolidado (~53 KB), extrai os dados estruturados e realiza `UPSERT` na tabela `salario_minimo`.
- **Escrita transacional:** Nenhuma. Carga em lote (batch), idempotente com resolução de conflitos por data de referência (`ano_mes`).

### Taxa de leitura e padrão de acesso

| # | Consulta | Frequência | Tipo | Latência Alvo | Acesso |
|---|---|---|---|---|---|
| 1 | Extração e raspagem da tabela no site DIEESE | 1 rodada/mês | lote | < 5 s | `GET https://www.dieese.org.br/analisecestabasica/salarioMinimo.html` |
| 2 | Cruzamento temporal Salário Mínimo x IPCA (Alimentos e Bebidas) | Média (notebooks/análises) | agregada | < 200 ms | `JOIN salario_minimo s ON s.ano_mes = i.ano_mes` |
| 3 | Série histórica de poder de compra (múltiplo necessário / nominal) | Alta (sob demanda) | pontual | < 50 ms | `SELECT ano_mes, salario_nominal, salario_necessario FROM salario_minimo` |
| 4 | Alinhamento com faturamento e ticket médio do lojista | Média (relatórios mensais) | agregada | < 100 ms | `JOIN salario_minimo s ON s.ano_mes = strftime(v.data_venda, '%Y-%m')` |

---

## 4. Restrições que a origem impõe

- **Ausência de API REST oficial:** O dado é fornecido exclusivamente como página web (HTML), exigindo rotina de raspagem (*web scraping*) baseada na tabela DOM (`<table rules="all">`).
- **Estrutura com cabeçalhos intermediários por ano:** A página organiza os meses sob linhas intermediárias de agrupamento com a classe `<tr class="subtitulo">` indicando o ano vigente (ex: `2026`, `2025`), demandando que o algoritmo de extração propague o ano para as linhas de meses subsequentes.
- **Codificação de caracteres (ISO-8859-1):** O servidor web do DIEESE envia a página codificada em `ISO-8859-1` (`latin1`), devendo ser decodificada explicitamente para não descaracterizar caracteres acentuados nos nomes dos meses (ex: "Março").
- **Formatação numérica em padrão brasileiro:** Os valores monetários contêm prefixo `R$`, separador de milhar com ponto e decimal com vírgula (ex: `R$ 7.565,86`), exigindo limpeza de strings e conversão para tipo numérico de ponto flutuante (*float/double*).
- **Periodicidade e defasagem de publicação:** Os cálculos do DIEESE para o mês de referência costumam ser publicados na primeira quinzena do mês subsequente (após a consolidação da pesquisa nas 17 capitais brasileiras).
