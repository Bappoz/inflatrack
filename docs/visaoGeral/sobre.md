# InflaTrack

Plataforma de dados que responde ao pequeno e médio lojista **quanto a inflação do setor dele subiu e qual reajuste ele precisa aplicar para não perder margem**.

Projeto Integrado da disciplina **Banco de Dados 2** — Engenharia de Software, FCTE/UnB.

---

## Pergunta de Gestão

> *Dado o setor, a praça e o período, qual foi a inflação acumulada dos produtos que este lojista vende — e qual o reajuste mínimo para preservar a margem?*

A caracterização completa da carga de trabalho e o detalhamento das 5 perguntas derivadas estão documentados em [Caracterização da Carga](carga.md).

---

## Fontes de Dados (SIDRA/IBGE)

Todas as séries temporais são obtidas diretamente da API do SIDRA/IBGE (`apisidra.ibge.gov.br`):

| Agregado | Índice | Período | Volume (Linhas) | Observação |
|---|---|---|---|---|
| [2938](https://sidra.ibge.gov.br/Tabela/2938) | IPCA | jul/2006 – dez/2011 | ~798 mil | Apenas 12 localidades; sem acumulado 12m |
| [1419](https://sidra.ibge.gov.br/Tabela/1419) | IPCA | jan/2012 – dez/2019 | ~2,19 mi | 464 categorias (POF 2008-2009) |
| [7060](https://sidra.ibge.gov.br/Tabela/7060) | IPCA | jan/2020 – | ~1,71 mi | 457 categorias (POF 2017-2018) |
| [7063](https://sidra.ibge.gov.br/Tabela/7063) | INPC | jan/2020 – | ~1,7 mi | Famílias de 1 a 5 salários mínimos |
| [1737](https://sidra.ibge.gov.br/Tabela/1737) | IPCA | dez/1979 – | 560 pontos | Número-índice geral Brasil (base dez/1993 = 100) |

---
