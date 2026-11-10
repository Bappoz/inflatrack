# Cesta Básica do PROCON (Preços de Varejo e Atacado)

Este documento registra as características arquiteturais e de negócio para a fonte de dados da **Pesquisa de Preços da Cesta Básica**, divulgada periodicamente pelos órgãos de proteção e defesa do consumidor (**PROCON**), com foco na apuração de preços reais de gôndola e atacarejos para produtos de alimentação, higiene e limpeza.

---

## 1. Motivação no InflaTrack

A pergunta central de gestão do InflaTrack é:
> *"Dado o setor, a praça e o período, qual foi a inflação acumulada dos produtos que este lojista vende — e qual o reajuste mínimo para preservar a margem?"*

Enquanto o **IPCA (SIDRA/IBGE)** fornece o índice percentual consolidado e as commodities fornecem o custo primário internacional, o levantamento do **PROCON** fornece a **medida física de preço (em R$) praticada nas lojas**:
* Permite comparar a inflação oficial com a variação nominal dos preços de gôndola.
* Serve como parâmetro direto de competitividade para o pequeno comerciante calibrar sua margem de lucro.
* Contém os mesmos itens essenciais que compõem o grupo Alimentação e Limpeza do IPCA (Arroz, Feijão, Óleo, Leite, Café, Açúcar, Carnes, Sabão em pó, Detergente, etc.).

---

## 2. Inventário da Fonte

| Atributo | Resposta |
| :--- | :--- |
| **Nome da fonte** | Pesquisa de Preços da Cesta Básica — PROCON |
| **Tipo** *(usuário / sistema / interna / terceiro)* | Terceiro |
| **Quem ou o que gera** | Fundação PROCON / Núcleos Regionais de Pesquisa e Estatística |
| **O que essa fonte contém** | Levantamentos mensais de preços mínimos, médios e máximos de itens essenciais de consumo familiar (alimentos, higiene pessoal e limpeza doméstica). |
| **Formato em que chega** | Arquivo tabular estruturado (CSV / XLSX) |
| **Volume estimado** | ~20 a 50 itens por mês por praça pesquisada (< 50 KB / mês) |
| **Frequência de chegada** | Mensal |
| **Vazão** | Baixa |
| **Pureza** | Alta (pesquisa amostral auditada por fiscais e pesquisadores de preços) |
| **Previsibilidade do formato** | Alta (esquema com `data_pesquisa`, `produto`, `unidade`, `preco_medio`, `praca` e `codigo_subitem_ipca`) |
| **Contém dado pessoal?** | Não (dados estatísticos de preços de bens de consumo) |
| **Base legal LGPD** | Não se aplica |
| **Retenção** | Permanente (preservada no Data Lake / DuckDB para séries analíticas) |
| **O que quebra se essa fonte falhar** | Perde-se a referência direta de preços nominais de mercado, inviabilizando a análise de dispersão de preços e defasagem de margem frente ao IPCA. |

---

## 3. Armazenamento e Camadas

* **Camada Raw**: Cópia fiel em `data/raw/procon/cesta_basica.csv.gz` preservando os dados brutos e metadados de ingestão.
* **Camada Bronze (Delta Lake)**:
  * `data/parquet/procon/resposta/`: Registro de auditoria das respostas/arquivos ingeridos.
  * `data/parquet/procon/cesta_basica/`: Tabela Delta com semântica de *insert-only* e deduplicação pela chave composta `(data_pesquisa, produto, praca, preco_medio)`.
* **DuckDB Analítico**: Espelhamento da tabela na base compartilhada em `bronze.procon_cesta_basica`.
* **Camada dbt (Silver)**: `stg_procon__cesta_basica` e `int_procon__mensal` para cálculo de variações percentuais e cruzamento com as séries do IPCA.
