# Consultas do Sistema

> **CONSULTAS QUE O SISTEMA PRECISA RESPONDER**

Esta página documenta o catálogo de perguntas de negócio que o **InflaTrack** deve responder. O modelo de dados e a arquitetura de armazenamento foram desenhados para priorizar o desempenho e a simplicidade das consultas mais frequentes.

---

## Catálogo de Consultas

| Nº | Consulta em português | Quem pergunta | Frequência | Tipo | Onde aparece |
|---|---|---|---|---|---|
| **1** | Quantas bicicletas estão emprestadas agora? | Equipe de manutenção | ~200 / dia | Agregada | Painel da equipe de manutenção |
| **2** | Qual foi a inflação acumulada do meu setor nos últimos 12 meses, para eu embasar o reajuste? | Lojista | ~5 / dia (por lojista) | Pontual | Tela inicial do lojista (card principal) |
| **3** | Em quais meses do ano historicamente ocorrem os maiores picos de inflação nos produtos que eu comercializo? | Lojista | ~1 / dia | Agregada | Relatório de sazonalidade |
| **4** | Como a inflação acumulada de 2006 até hoje impactou o poder de compra da categoria que eu vendo? | Lojista | < 1 / dia | Agregada | Relatório "Poder de Compra" |
| **5** | Qual a diferença entre a inflação geral e a da minha região nos últimos 5 anos, para eu planejar expansão ou preço local? | Lojista | ~1 / dia | Agregada | Tela de comparação regional / mapa |
| **6** | Qual taxa de reajuste mínima devo aplicar aos meus produtos para não perder margem em relação ao IPCA do último ano? | Lojista | ~10 / dia | Pontual (gera escrita) | Tela de sugestão de reajuste e botão "aplicar reajuste" |
| **7** | Como a alta do Dólar no último semestre impactou a inflação (IPCA) dos produtos importados do meu setor? | Lojista / Analista | ~5 / dia | Agregada | Relatório "Impacto Cambial" |
| **8** | Qual a relação entre meses de seca (baixa precipitação/clima extremo) e os picos de inflação nos produtos agrícolas que eu vendo? | Lojista (Setor Alimentício) | ~2 / dia | Agregada | Painel "Sazonalidade Climática" |
| **9** | A inflação atual está ocorrendo num período de aquecimento econômico (PIB em alta) ou em recessão? | Planejamento Estratégico | < 1 / dia (trimestral) | Agregada | Relatório de Contexto Macroeconômico |
| **10** | Com a Selic atual, compensa eu repassar a inflação agora para o cliente, ou o custo de oportunidade (juros) compensa absorver a margem temporariamente? | Lojista (Gestor Financeiro) | ~10 / dia | Pontual (cálculo rápido) | Ferramenta "Simulador de Repasse vs Rendimento" |
| **11** | Qual é a correlação matemática entre os picos do Dólar (volatilidade intraday) e o encarecimento imediato da cesta de produtos importados que eu vendo? | Algoritmo / Lojista | ~1 / dia | Agregada | Ferramenta "Simulador de Repasse Cambial" |
| **12** | Considerando o aperto monetário (alta da Selic) nos últimos 3 meses, as vendas do meu setor retraíram a ponto de eu ter que absorver parte da inflação em vez de repassar ao cliente? | Planejamento Estratégico | < 5 / mês | Agregada | Relatório de Contexto Macroeconômico |

---

## Detalhamento Técnico das Consultas

### Consulta 1: Quantidade de empréstimos ativos
* **Pergunta**: Quantas bicicletas estão emprestadas agora?
* **Quem pergunta**: Equipe de manutenção (~200/dia)
* **Tipo**: Agregada
* **Modelo ideal**: Relacional *(sofrida em: Documento)*
* **Por quê**: Exige contar registros com filtro — trivial com índice e SQL.
* **Onde aparece**: Painel da equipe de manutenção
* **Observações**: Precisa refletir o estado do momento.

---

### Consulta 2: Inflação acumulada do setor (12 meses)
* **Pergunta**: Qual foi a inflação acumulada do meu setor nos últimos 12 meses, para eu embasar o reajuste?
* **Quem pergunta**: Lojista (~5/dia por lojista)
* **Tipo**: Pontual
* **Modelo ideal**: Relacional *(sofrida em: Documento)*
* **Por quê**: O IBGE já publica o acumulado em 12 meses pronto (variável 2265). A consulta é um filtro por `(subitem, localidade, mês)` que devolve uma linha — índice composto resolve em milissegundos. Em documento exigiria abrir o documento da categoria inteira.
* **Onde aparece**: Tela inicial do lojista (card principal)
* **Observações**: Armadilha: a variável 2265 NÃO existe na tabela 2938 (2006-2011). Para esse período o acumulado em 12 meses tem de ser calculado a partir da variação mensal.

---

### Consulta 3: Picos históricos de inflação por produto
* **Pergunta**: Em quais meses do ano historicamente ocorrem os maiores picos de inflação nos produtos que eu comercializo?
* **Quem pergunta**: Lojista (~1/dia)
* **Tipo**: Agregada
* **Modelo ideal**: Relacional *(sofrida em: Chave-Valor)*
* **Por quê**: Agregação por mês-do-ano sobre ~240 observações mensais por subitem/localidade. Trivial com `GROUP BY`; impossível de indexar num armazenamento por chave.
* **Onde aparece**: Relatório de sazonalidade
* **Observações**: Exige a série completa (2938 + 1419 + 7060) unificada. É a consulta que mais depende da união correta das três tabelas de origem.

---

### Consulta 4: Impacto histórico acumulado no poder de compra (desde 2006)
* **Pergunta**: Como a inflação acumulada de 2006 até hoje impactou o poder de compra da categoria que eu vendo?
* **Quem pergunta**: Lojista (< 1/dia)
* **Tipo**: Agregada
* **Modelo ideal**: Relacional *(sofrida em: Documento)*
* **Por quê**: É produto acumulado, não soma: `exp(sum(ln(1+v/100)))` sobre 241 variações mensais encadeadas. Window function resolve numa passada; em documento seria preciso trazer a série inteira para a aplicação.
* **Onde aparece**: Relatório "Poder de Compra"
* **Observações**: Atravessa as três tabelas de origem e as duas revisões de estrutura da cesta. Se o subitem trocou de código, a série quebra e o resultado sai errado sem levantar erro — precisa de teste de continuidade.

---

### Consulta 5: Comparação Regional vs. Inflação Geral
* **Pergunta**: Qual a diferença entre a inflação geral e a da minha região nos últimos 5 anos, para eu planejar expansão ou preço local?
* **Quem pergunta**: Lojista (~1/dia)
* **Tipo**: Agregada
* **Modelo ideal**: Relacional *(sofrida em: Chave-Valor)*
* **Por quê**: Autojunção da tabela de fato com ela mesma: `localidade = Brasil` de um lado, a região do lojista do outro, mesma classificação e mesmo mês (um `JOIN`).
* **Onde aparece**: Tela de comparação regional / mapa
* **Observações**: Só existem 17 localidades. Se a praça do lojista não é uma delas, a resposta honesta é "sua cidade não é medida pelo IPCA" — decidir isso no produto em vez de escolher a região mais próxima em silêncio.

---

### Consulta 6: Sugestão de Taxa de Reajuste Mínima
* **Pergunta**: Qual taxa de reajuste mínima devo aplicar aos meus produtos para não perder margem em relação ao IPCA do último ano?
* **Quem pergunta**: Lojista (~10/dia — ação principal)
* **Tipo**: Pontual (gera escrita)
* **Modelo ideal**: Relacional *(sofrida em: Qualquer modelo que separe as duas metades do sistema)*
* **Por quê**: É a única consulta que junta o mundo transacional do lojista (`Produto`) com o mundo de referência do IBGE (`Observação de IPCA`), pela FK `codigo_subitem_ipca`. Sem integridade referencial, junta com a categoria errada silenciosamente.
* **Onde aparece**: Tela de sugestão de reajuste e botão "aplicar reajuste"
* **Observações**: É o ponto OLTP do sistema: aplicar o reajuste insere linha em `Reajuste de preço` e atualiza o preço do produto — as duas coisas na mesma transação.

---

### Consulta 7: Impacto Cambial (Dólar vs. IPCA de Importados)
* **Pergunta**: Como a alta do Dólar no último semestre impactou a inflação (IPCA) dos produtos importados do meu setor?
* **Quem pergunta**: Lojista / Analista (~5/dia)
* **Tipo**: Agregada
* **Modelo ideal**: Série temporal / Banco colunar *(sofrida em: Documento JSON)*
* **Por quê**: Exige agrupar janelas de tempo de alta volatilidade e fazer um JOIN temporal com o IPCA. No modelo de série temporal colunar (Parquet), as contas matemáticas ao longo das datas são vetorizadas e respondidas em milissegundos, enquanto em JSON a aplicação travaria abrindo os nós de dias.
* **Onde aparece**: Relatório "Impacto Cambial"
* **Observações**: Mede se o lojista sofre repasse cambial direto ou atrasado.

---

### Consulta 8: Sazonalidade Climática vs. Inflação Agrícola
* **Pergunta**: Qual a relação entre meses de seca (baixa precipitação/clima extremo) e os picos de inflação nos produtos agrícolas que eu vendo?
* **Quem pergunta**: Lojista - Setor Alimentício (~2/dia)
* **Tipo**: Agregada
* **Modelo ideal**: Relacional ou Série temporal *(sofrida em: Documento)*
* **Por quê**: Requer agrupar a precipitação diária por região e mês (`GROUP BY`) e cruzar com o IPCA regional. Documentos aninhados deixariam o JOIN caótico.
* **Onde aparece**: Painel "Sazonalidade Climática"
* **Observações**: Valida a tese de que choque de oferta por quebra de safra é o que mais gera inflação no subitem.

---

### Consulta 9: Contexto Macroeconômico (Inflação vs. PIB)
* **Pergunta**: A inflação atual está ocorrendo num período de aquecimento econômico (PIB em alta) ou em recessão?
* **Quem pergunta**: Planejamento Estratégico (< 1/dia - trimestral)
* **Tipo**: Agregada
* **Modelo ideal**: Relacional *(sofrida em: Chave-Valor)*
* **Por quê**: Exige agrupar os meses do IPCA em trimestres lógicos para fazer o match exato com o PIB do IBGE.
* **Onde aparece**: Relatório de Contexto Macroeconômico
* **Observações**: Cruza o fator Demanda (PIB) com o Preço (IPCA).

---

### Consulta 10: Custos de Oportunidade (Selic vs. Repasse de Margem)
* **Pergunta**: Com a Selic atual, compensa eu repassar a inflação agora para o cliente, ou o custo de oportunidade (juros) compensa absorver a margem temporariamente?
* **Quem pergunta**: Lojista / Gestor Financeiro (~10/dia)
* **Tipo**: Pontual (cálculo rápido)
* **Modelo ideal**: Série temporal *(sofrida em: Chave-Valor)*
* **Por quê**: O banco chave-valor exige saber a data exata. Já a evolução da Selic exige avaliar o intervalo de 3 meses de juros acumulados (Range Scan). O modelo de série temporal trata fatias de tempo nativamente com eficiência matemática.
* **Onde aparece**: Ferramenta "Simulador de Repasse vs Rendimento"
* **Observações**: Cruza as entidades Taxa de Juros e IPCA na mesma janela temporal.

---

### Consulta 11: Correlação de Volatilidade Cambial Intraday
* **Pergunta**: Qual é a correlação matemática entre os picos do Dólar (volatilidade intraday) e o encarecimento imediato da cesta de produtos importados que eu vendo?
* **Quem pergunta**: Algoritmo de Previsão de Preços / Lojista (~1/dia)
* **Tipo**: Agregada
* **Modelo ideal**: Série temporal colunar (Parquet / DuckDB) *(sofrida em: Documento JSON ou Chave-Valor)*
* **Por quê**: A consulta exige agrupar os dias em semanas (média móvel da variação cambial) e cruzar com os produtos do lojista no mesmo período de tempo. Bancos colunares calculam agregações de "janela de tempo" de forma vetorizada, nativa e instantânea.
* **Onde aparece**: Ferramenta "Simulador de Repasse Cambial"
* **Observações**: Esta consulta valida o uso do formato Parquet. Ela junta o mundo do BCB (Câmbio) com o banco transacional (Vendas do Lojista).

---

### Consulta 12: Análise de Aperto Monetário e Vendas do Setor
* **Pergunta**: Considerando o aperto monetário (alta da Selic) nos últimos 3 meses, as vendas do meu setor retraíram a ponto de eu ter que absorver parte da inflação em vez de repassar ao cliente?
* **Quem pergunta**: Planejamento Estratégico / Gestor Financeiro (< 5/mês)
* **Tipo**: Agregada
* **Modelo ideal**: Série temporal *(sofrida em: Chave-Valor)*
* **Por quê**: Analisar "alta ao longo de 3 meses" requer varredura de intervalo (Range Scan). Séries temporais fatiam intervalos de 90 dias com um único comando matemático.
* **Onde aparece**: Relatório de Contexto Macroeconômico / Viabilidade de Repasse
* **Observações**: Cruza simultaneamente os 3 mundos do pipeline: IPCA (Inflação), Banco Transacional (Vendas) e Selic (Custo do Crédito).

---

