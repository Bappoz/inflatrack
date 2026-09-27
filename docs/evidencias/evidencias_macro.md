# Evidências - Macroeconomia

Números, volumetrias e anomalias aferidos durante a construção e carga do módulo macroeconômico (Dólar, Selic e Commodities) contra a API do Banco Central e no banco analítico DuckDB.

## 1. Volumetria e Resiliência (medido em 2026-09-25)

A carga da Macroeconomia utilizou uma estratégia ETL diferenciada, medindo os seguintes parâmetros operacionais no terminal local:

| Etapa / Métrica | Resultado Medido / Observado |
|---|---|
| Período da Carga (Macro) | 01/01/2020 a 31/07/2026 |
| Volume Dólar (Olinda) | **2.403 dias civis** informados pela execução original e carregados no DuckDB |
| Volume Selic (SGS) | **2.403 dias civis** informados pela execução original e carregados no DuckDB |
| Deduplicação | A transformação ordena `dataHoraCotacao` e mantém a última cotação caso a origem devolva mais de uma linha na mesma data. |
| Resiliência do Banco (Idempotência) | Testado cenário de sobreposição de datas: o `ON CONFLICT DO UPDATE` do DuckDB processou a carga de um mês repetido sobrescrevendo os dados de forma perfeita, sem inflar o volume total de 2.403 linhas. |
| Resiliência de rede | Os clientes usam timeout de 30 segundos e propagam erros HTTP; bloqueios ou indisponibilidade não são convertidos em falso sucesso. |

## 2. Cobertura de Testes Automatizados (pytest)

Até a integração desta frente, o repositório não possuía cobertura automatizada de testes (o comando padrão reportava `collected 0 items`). A frente de Macroeconomia inaugurou a cobertura de qualidade estática:

- Criados e isolados os testes em `tests/test_dolar_olinda.py` e `tests/test_selic_sgs.py` utilizando *Mocks* nativos (`unittest.mock`).
- Testado o comportamento do Dólar em dias úteis (extração correta da chave `"value"`) e em dias sem pregão (array vazio tratado corretamente).
- A revisão ampliou a suíte para clientes HTTP, payload inválido, preenchimento do calendário e idempotência no DuckDB.

## 3. Revalidação da revisão (2026-09-26)

- Janela real consultada: 19–25/09/2026, incluindo sábado e domingo no início.
- Olinda/PTAX e SGS responderam com cinco dias úteis cada.
- As duas tabelas terminaram com sete dias civis: cinco `observado = true` e
  dois `observado = false`.
- O cruzamento diário entre dólar e Selic retornou as sete datas sem lacunas.
- Oito testes automatizados passaram, incluindo duas cargas repetidas sem
  duplicação de chaves.
