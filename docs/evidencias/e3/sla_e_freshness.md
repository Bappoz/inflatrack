# Evidência E3 — Métricas de Freshness e SLA Declarado

Em conformidade com o checklist de aceite da Entrega 3:
> *"Métrica de freshness e SLA declarado para ao menos uma tabela de consumo"*

Documentamos nesta evidência as políticas formais de SLA (*Service Level Agreement*), tolerâncias operacionais, limites volumétricos e a implementação dos *Asset Checks* nativos no Dagster para a camada macroeconômica.

---

## 1. Declaração Formal de SLAs e Frescura dos Dados

| Ativo / Tabela | Camada / Tipo | Frequência de Divulgação Oficial | SLA Declarado | Volume Mínimo | Alerta de Desatualização |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **`silver.int_macroeconomia__mensal`** | **Tabela de Consumo** (Silver Intermediate) | Mensal (agregado das séries diárias) | **Até 45 dias corridos** após o início do mês de referência | $\ge 12$ meses | `WARN` no Dagster com metadados de defasagem |
| **`dolar_duckdb`** (`bronze.dolar_boletim`) | Ingestão / Carga (Bronze) | Diária (dias úteis, fechamento até 19h) | **D-1 útil** (tolerância de até 5 dias corridos) | $\ge 100$ linhas | `WARN` no Dagster caso falte coleta recente |
| **`selic_duckdb`** (`bronze.selic_taxa`) | Ingestão / Carga (Bronze) | Diária (dias úteis, divulgação D+1 útil) | **D+1 útil** (tolerância de até 5 dias corridos) | $\ge 100$ linhas | `WARN` no Dagster caso falte coleta recente |

### Justificativa dos Prazos de SLA:
1. **Série Mensal Consolidada (`int_macroeconomia__mensal`):** Como os modelos preditivos e a Gold dependem de janelas móveis de 12 meses (`mm12`) e volatilidade anualizada, o volume mínimo estrito é de 12 observações mensais. A defasagem de até 45 dias permite acomodar o encerramento do mês civil e o período de apuração antes do reajuste.
2. **Fontes Diárias do Banco Central (Dólar e Selic):** O Banco Central do Brasil opera em dias úteis bancários. Finais de semana regulares e feriados prolongados (ex: Carnaval, Páscoa) introduzem naturalmente até 4 a 5 dias corridos de intervalo sem publicação de novos boletins oficiais. Portanto, a tolerância de até 5 dias corridos evita alarmes falsos operacionais.

---

## 2. Implementação Técnica no Dagster (`orchestration/assets/checks.py`)

No Dagster 1.13+, a verificação de SLA e integridade analítica é implementada via decorador `@asset_check`. 

O módulo [`orchestration/assets/checks.py`](file:///home/americo/Faculdade/Bancos%202/inflatrack/orchestration/assets/checks.py) conecta-se em modo leitura ao DuckDB (`data/duckdb/inflatrack.duckdb`) e inspeciona:
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
        "mes_mais_recente": "2026-10-01",
        "dias_atraso": 31,
        "total_meses": 82,
        "minimo_meses_requerido": 12,
    },
    description="Macroeconomia até 2026-10-01 (31d defasagem, 82 meses). SLA: CUMPRIDO."
)
```

### Comportamento em Caso de Violação:
- **Dado Desatualizado além do SLA:** O check marca `passed=False` com `severity=AssetCheckSeverity.WARN`. A interface do Dagster exibe um aviso amarelo de atenção e registra nos metadados a defasagem exata, sem interromper imediatamente a execução dos pipelines a jusante.
- **Tabela Vazia ou Banco Inacessível:** O check marca `passed=False` com `severity=AssetCheckSeverity.ERROR`, sinalizando bloqueio operacional crítico.

---

## 3. Validação Automatizada da Suíte

A conformidade do registro e execução dos checks no orquestrador é assegurada pelos testes em [`tests/orchestration/test_checks.py`](file:///home/americo/Faculdade/Bancos%202/inflatrack/tests/orchestration/test_checks.py):
- `test_asset_checks_registrados_nas_definicoes`: Valida a presença dos checks no grafo de definições do Dagster.
- `test_check_dolar_executa_e_valida_sla`: Executa e valida o SLA do Dólar.
- `test_check_selic_executa_e_valida_sla`: Executa e valida o SLA da Selic.
- `test_check_macroeconomia_mensal_executa_e_valida_sla`: Executa e valida o SLA da tabela de consumo intermediária.
- `test_check_falha_quando_duckdb_nao_existe`: Valida a severidade de erro quando o banco não existe.

Todos os 5 testes rodam em menos de 3 segundos com status 100% `PASS`.

---

## 4. Roteiro de Expansão (Revisão da E3 Pós-Unificação das Branches)

Durante o desenvolvimento isolado da branch `feat/e3-pedro`, as tabelas da Bronze de outras trilhas (`bronze.pib_valor`, `bronze.commodities_cotacao`, etc.) ainda não estavam populadas no ambiente local. 

Conforme planejado:
- **Na Entrega da Trilha:** O SLA foi validado e formalizado para a tabela de consumo de macroeconomia e seus ativos de origem.
- **Na Revisão Geral Pós-Merge:** Assim que as branches dos demais integrantes forem unificadas na branch principal da E3, novos *Asset Checks* análogos serão estendidos em `orchestration/assets/checks.py` para cobrir 100% das fontes (PIB setorial, commodities Alpha Vantage, clima INMET, salário mínimo DIEESE e IPCA/INPC).
