# InflaTrack

Plataforma de dados que responde ao pequeno e médio lojista **quanto a inflação do setor dele subiu e qual reajuste ele precisa aplicar para não perder margem**.

Projeto Integrado da disciplina **Banco de Dados 2** — Engenharia de Software, FCTE/UnB.

---

## Pergunta de Gestão

> *Dado o setor, a praça e o período, qual foi a inflação acumulada dos produtos que este lojista vende — e qual o reajuste mínimo para preservar a margem?*

A caracterização completa da carga de trabalho e o detalhamento das 5 perguntas derivadas estão documentados em [Caracterização da Carga](../carga.md).

---

## Fontes de Dados

| Nome | Descrição |
|---|---|
| [SIDRA](../fontes/sidra.md) | Sistema IBGE de Recuperação Automática. Responsável pelo fornecimento das séries temporais oficiais dos índices de inflação (IPCA e INPC) via API (`apisidra.ibge.gov.br`), contemplando variações mensais, acumuladas e números-índice por categoria e localidade. |

---
