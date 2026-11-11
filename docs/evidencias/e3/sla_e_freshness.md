# Evidência E3 — Métricas de Freshness e SLA Declarado

Em conformidade com o checklist de aceite da Entrega 3:
> *"Métrica de freshness e SLA declarado para ao menos uma tabela de consumo"*

Documentamos nesta evidência as políticas formais de SLA (*Service Level Agreement*), tolerâncias operacionais, limites volumétricos e a implementação dos *Asset Checks* nativos no Dagster para a camada macroeconômica. Na integração da E3, o mesmo contrato foi estendido às demais fontes que chegam ao DuckDB (seção 1, linhas abaixo da Selic).

---

## 1. Declaração Formal de SLAs e Frescura dos Dados

| Ativo / Tabela | Camada / Tipo | Frequência de Divulgação Oficial | SLA Declarado | Volume Mínimo | Alerta de Desatualização |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **`gold.fct_macroeconomia_mensal`** | **Tabela de Consumo** (Gold, copiada para `serie` e lida pelo Metabase) | Mensal (agregado das séries diárias) | **Até 45 dias corridos** após o início do mês de referência | $\ge 12$ meses | `WARN` no Dagster com metadados de defasagem |
| **`dolar_duckdb`** (`bronze.dolar_boletim`) | Ingestão / Carga (Bronze) | Diária (dias úteis, fechamento até 19h) | **D-1 útil** (tolerância de até 5 dias corridos) | $\ge 100$ linhas | `WARN` no Dagster caso falte coleta recente |
| **`selic_duckdb`** (`bronze.selic_taxa`) | Ingestão / Carga (Bronze) | Diária (dias úteis, divulgação D+1 útil) | **D+1 útil** (tolerância de até 5 dias corridos) | $\ge 100$ linhas | `WARN` no Dagster caso falte coleta recente |
| **`ipca_duckdb`** (`bronze.ipca_observacao`) | Ingestão / Carga (Bronze) | Mensal (IBGE, ~dia 10 do mês seguinte) | **75 dias** após o início do mês de referência | $\ge 1.000.000$ linhas | `WARN` com metadados de defasagem |
| **`salario_minimo_duckdb`** (`bronze.salario_minimo_mes`) | Ingestão / Carga (Bronze) | Mensal (DIEESE) | **75 dias** após o início do mês de referência | $\ge 387$ meses | `WARN` com metadados de defasagem |
| **`pib_duckdb`** (`bronze.pib_valor`) | Ingestão / Carga (Bronze) | Trimestral (IBGE, ~2 meses após o trimestre) | **260 dias** após o início do trimestre | $\ge 920$ linhas | `WARN` com metadados de defasagem |
| **`pib_internacional_duckdb`** (`bronze.pib_internacional_indicador`) | Ingestão / Carga (Bronze) | Anual (Banco Mundial) | **730 dias** após o fim do ano de referência | $\ge 100$ linhas | `WARN` com metadados de defasagem |
| **`clima_duckdb`** (`bronze.clima_estacao`) | Ingestão / Carga (Bronze) | Catálogo coletado todo dia | **7 dias** desde a última coleta (`_ingerido_em`) | $\ge 604$ estações | `WARN` no Dagster caso falte coleta recente |
| **`commodities_duckdb`** (`bronze.commodities_cotacao`) | Ingestão / Carga (Bronze) | Diária ou mensal, por série | Diária: **7 dias**; mensal: **75 dias** após o início do mês | $\ge 100$ linhas | `WARN` listando as séries atrasadas |

### Justificativa dos Prazos de SLA:
1. **Câmbio x juros na Gold (`fct_macroeconomia_mensal`):** Como os modelos preditivos e a Gold dependem de janelas móveis de 12 meses (`mm12`) e volatilidade anualizada, o volume mínimo estrito é de 12 observações mensais. A defasagem de até 45 dias permite acomodar o encerramento do mês civil e o período de apuração antes do reajuste.
2. **Fontes Diárias do Banco Central (Dólar e Selic):** O Banco Central do Brasil opera em dias úteis bancários. Finais de semana regulares e feriados prolongados (ex: Carnaval, Páscoa) introduzem naturalmente até 4 a 5 dias corridos de intervalo sem publicação de novos boletins oficiais. Portanto, a tolerância de até 5 dias corridos evita alarmes falsos operacionais.
3. **IPCA/INPC e Salário Mínimo:** o IBGE divulga o mês por volta do dia 10 do mês seguinte e o DIEESE atualiza a tabela no começo dele. Antes da divulgação, o último mês da tabela começou há até ~70 dias; 75 cobre o pior caso sem alarme falso. O mínimo de 387 meses do salário mínimo é o `VOLUME_MINIMO_REFERENCIA` da Bronze.
4. **PIB (SIDRA 1846):** `data_referencia` é o primeiro dia do trimestre e o IBGE divulga o trimestre ~2 meses depois de ele acabar, então logo antes de uma divulgação o último trimestre começou há ~247 dias; 260 dá folga. O mínimo de 920 linhas é 10 anos × 4 trimestres × 23 categorias.
5. **PIB internacional:** o Banco Mundial só publica o ano fechado, no 2º semestre do ano seguinte; o ano mais recente pode ter 2 anos de defasagem. O guarda é grosseiro de propósito: pega fonte parada há anos, não atraso de semanas.
6. **Clima:** mede-se a coleta do **catálogo de estações** (`clima_job`, diária), com mínimo de 604 estações (referência da Bronze, 671, menos 10%). As medições diárias (`clima_medicoes`) ficam de fora: a coleta é manual, por estação e intervalo, e não há cadência para declarar.
7. **Commodities:** a Alpha Vantage mistura séries diárias e mensais; cada série é avaliada contra o prazo do `intervalo` dela, e o metadado `series_atrasadas` lista as paradas.

---

## 2. Implementação Técnica no Dagster (`orchestration/assets/checks.py`)

No Dagster 1.13+, a verificação de SLA e integridade analítica é implementada via decorador `@asset_check`. 

Cada fonte é um `Sla` (tabela, expressão da data de referência, prazo, volume mínimo e texto do SLA) e uma única função, `avaliar(sla)`, faz a verificação; commodities usa `avaliar_commodities()`, que repete a conta por série. Tabela ausente (a carga ainda não rodou) vira `ERROR` com mensagem, não exceção.

O módulo `orchestration/assets/checks.py` conecta-se em modo leitura ao DuckDB, dentro do pool `duckdb_writer`, (`data/duckdb/inflatrack.duckdb`) e inspeciona:
1. A data mais recente observada (`max(data_referencia)` ou `max(mes_referencia)`);
2. O total de registros acumulados (`count(*)`);
3. A diferença em dias em relação à data corrente do sistema.

### Exemplo de Resposta de Check (`AssetCheckResult`):
```python
AssetCheckResult(
    passed=True,
    severity=AssetCheckSeverity.WARN,
    metadata={
        "sla_declarado": "Mensal (máximo 45 dias após início do mês)",
        "data_mais_recente": "2026-10-01",
        "dias_atraso": 31,
        "atraso_maximo_dias": 45,
        "total_linhas": 82,
        "volume_minimo_esperado": 12,
    },
    description="Macroeconomia até 2026-10-01 (31d de defasagem, 82 meses). SLA: CUMPRIDO.",
)
```

### Comportamento em Caso de Violação:
- **Dado Desatualizado além do SLA:** O check marca `passed=False` com `severity=AssetCheckSeverity.WARN`. A interface do Dagster exibe um aviso amarelo de atenção e registra nos metadados a defasagem exata, sem interromper imediatamente a execução dos pipelines a jusante.
- **Tabela Vazia ou Banco Inacessível:** O check marca `passed=False` com `severity=AssetCheckSeverity.ERROR`, sinalizando bloqueio operacional crítico.

---

## 3. Validação Automatizada da Suíte

A conformidade do registro e execução dos checks no orquestrador é assegurada pelos testes em `tests/orchestration/test_checks.py`, que rodam contra um DuckDB temporário:
- `test_asset_checks_registrados_nas_definicoes`: Valida a presença dos checks no grafo de definições do Dagster.
- `test_check_dolar_executa_e_valida_sla`: Executa e valida o SLA do Dólar.
- `test_check_selic_executa_e_valida_sla`: Executa e valida o SLA da Selic.
- `test_check_macroeconomia_mensal_executa_e_valida_sla`: Executa e valida o SLA da tabela de consumo da Gold.
- `test_check_falha_quando_duckdb_nao_existe`: Valida a severidade de erro quando o banco não existe.

Na extensão para as demais fontes, os testes parametrizados cobrem os 9 checks: registro no grafo e pool `duckdb_writer`; fonte em dia cumpre o SLA; tabela ausente vira `ERROR` sem exceção; fonte atrasada vira `WARN`; e `test_commodities_aponta_a_serie_atrasada` mostra a série diária parada acusada enquanto a mensal, com a mesma idade, segue no prazo. O arquivo tem 33 testes, todos `PASS`.

Os 9 checks também foram executados com dados reais, dentro dos jobs do Dagster, numa cópia isolada da árvore de trabalho (2026-11-09; o IPCA, já coletado, veio do banco de desenvolvimento). Todos cumpriram o SLA:

| Check | Resultado em 2026-11-09 |
|---|---|
| Dólar | até 2026-11-06 (3 dias), 1.720 linhas |
| Selic | até 2026-11-06 (3 dias), 1.719 linhas |
| Macroeconomia (Gold) | até 2026-11-01 (8 dias), 83 meses |
| IPCA/INPC | até 2026-09-01 (69 dias), 9.116.436 linhas |
| Salário mínimo | até 2026-09-01 (69 dias), 387 meses |
| PIB | até 2026-04-01 (222 dias), 1.058 linhas |
| PIB internacional | até 2025-12-31 (313 dias), 396 linhas |
| Catálogo de clima | coleta de 2026-11-09 (0 dia), 668 estações |
| Commodities | 9 de 9 séries em dia, 31.952 linhas |

---

## 4. Roteiro de Expansão (Revisão da E3 Pós-Unificação das Branches)

Durante o desenvolvimento isolado da branch `feat/e3-pedro`, as tabelas da Bronze de outras trilhas (`bronze.pib_valor`, `bronze.commodities_cotacao`, etc.) ainda não estavam populadas no ambiente local. 

Conforme planejado:
- **Na Entrega da Trilha:** O SLA foi validado e formalizado para a tabela de consumo de macroeconomia e seus ativos de origem.
- **Na Revisão Geral Pós-Merge (feita):** Com as branches unificadas, os *Asset Checks* análogos foram estendidos em `orchestration/assets/checks.py` ao PIB setorial, PIB internacional, commodities Alpha Vantage, catálogo de clima INMET, salário mínimo DIEESE e IPCA/INPC (seção 1).
- **Ainda de fora:** as medições diárias do clima (coleta manual, sem cadência) e um calendário de dias úteis do BCB para tornar exato o prazo de 5 dias de Dólar e Selic.

---

## 5. Decisões registradas

| Data | Decisão | Motivo | Alternativa descartada |
|---|---|---|---|
| 2026-11-09 | O prazo de **75 dias** do IPCA/INPC e do salário mínimo é o SLA declarado do grupo | Cobre o pior caso (mês ainda não divulgado, ~70 dias desde o início do mês) sem alarme falso; com a tabela até set/2026, o atraso medido em 2026-11-09 foi de 69 dias | 45 dias, como a Gold de macroeconomia: acusaria atraso nos primeiros ~15 dias de todo mês, antes de a fonte divulgar |
