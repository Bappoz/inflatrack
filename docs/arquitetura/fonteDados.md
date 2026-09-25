| Nome | Descrição |
|---|---|
| [SIDRA](../fontes/sidra.md) | Sistema IBGE de Recuperação Automática. Responsável pelo fornecimento das séries temporais oficiais dos índices de inflação (IPCA e INPC) via API (`apisidra.ibge.gov.br`), contemplando variações mensais, acumuladas e números-índice por categoria e localidade. |
| [Commodities e Energia (Alpha Vantage)](../fontes/commodities.md) | API REST da Alpha Vantage que fornece séries históricas de preços de energia (Petróleo WTI, Brent, Gás Natural) e agrícolas (Trigo, Milho, Algodão, Açúcar, Café e índice global), com frequência diária para energia e mensal para agrícolas. Usada como variável explicativa e para treinamento dos modelos de previsão dos preços. |
| [PIB da China (World Bank)](../fontes/pib_china.md) | API REST pública do Banco Mundial. Fornece as séries temporais de crescimento percentual do PIB e valor bruto da China, atuando como indicador antecedente de demanda global por commodities e repasse de custos na inflação brasileira. |

---