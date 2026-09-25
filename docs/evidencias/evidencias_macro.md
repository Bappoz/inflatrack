# Evidências - Macroeconomia

Números, volumetrias e anomalias aferidos durante a construção e carga do módulo macroeconômico (Dólar, Selic e Commodities) contra a API do Banco Central e no banco analítico DuckDB.

## 1. Volumetria e Resiliência (medido em 2026-09-25)

A carga da Macroeconomia utilizou uma estratégia ETL diferenciada, medindo os seguintes parâmetros operacionais no terminal local:

| Etapa / Métrica | Resultado Medido / Observado |
|---|---|
| Período da Carga (Macro) | 01/01/2020 a 31/07/2026 |
| Volume Dólar (Olinda) | **2.403 registros diários** processados no Parquet e carregados no DuckDB |
| Volume Selic (SGS) | **2.403 registros diários** processados no Parquet e carregados no DuckDB |
| Anomalia Intradiária | A API Olinda devolvia múltiplos boletins por dia, gerando o erro `cannot reindex on an axis with duplicate labels` no Pandas. **Corrigido** aplicando o filtro de fechamento (`keep="last"`). |
| Resiliência do Banco (Idempotência) | Testado cenário de sobreposição de datas: o `ON CONFLICT DO UPDATE` do DuckDB processou a carga de um mês repetido sobrescrevendo os dados de forma perfeita, sem inflar o volume total de 2.403 linhas. |
| Restrições de Rede (WAF) | O firewall (Azure Front Door) do Banco Central barra agressivamente múltiplas requisições sequenciais originadas de IPs de Data Centers corporativos com erro `403 Forbidden`. IPs residenciais concluem a carga histórica inteira (6+ anos) sem interrupções. |

## 2. Cobertura de Testes Automatizados (pytest)

Até a integração desta frente, o repositório não possuía cobertura automatizada de testes (o comando padrão reportava `collected 0 items`). A frente de Macroeconomia inaugurou a cobertura de qualidade estática:

- Criados e isolados os testes em `tests/test_dolar_olinda.py` e `tests/test_selic_sgs.py` utilizando *Mocks* nativos (`unittest.mock`).
- Testado o comportamento do Dólar em dias úteis (extração correta da chave `"value"`) e em dias sem pregão (array vazio tratado corretamente).
- **Tempo de execução:** `0.06s` para 3 testes 100% aprovados.
