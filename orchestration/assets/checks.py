"""Asset checks de qualidade de dados, integridade de volume e SLA/Freshness no Dagster.

Atende ao requisito da Entrega 3:
- Métrica de freshness e SLA declarado para tabelas de consumo e séries macroeconômicas.
"""

from datetime import date
from pathlib import Path

import duckdb
from dagster import (
    AssetCheckExecutionContext,
    AssetCheckResult,
    AssetCheckSeverity,
    AssetKey,
    asset_check,
)

from orchestration.assets.dolar import dolar_duckdb
from orchestration.assets.selic import selic_duckdb

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")


@asset_check(
    asset=dolar_duckdb,
    description="SLA de atualização e volume mínimo para cotações do Dólar comercial PTAX.",
)
def check_dolar_freshness_e_volume(
    context: AssetCheckExecutionContext,
) -> AssetCheckResult:
    """SLA: D-1 útil (tolerância de até 5 dias corridos para feriados e fins de semana)."""
    if not DB_PADRAO.exists():
        return AssetCheckResult(
            passed=False,
            severity=AssetCheckSeverity.ERROR,
            description=f"Banco de dados DuckDB não encontrado em {DB_PADRAO}",
        )

    con = duckdb.connect(str(DB_PADRAO), read_only=True)
    try:
        resultado = con.execute(
            "select max(data_referencia), count(*) from bronze.dolar_boletim"
        ).fetchone()
    finally:
        con.close()

    if not resultado or resultado[0] is None:
        return AssetCheckResult(
            passed=False,
            severity=AssetCheckSeverity.ERROR,
            description="Tabela bronze.dolar_boletim está vazia",
        )

    max_data: date = resultado[0]
    total_linhas: int = resultado[1]

    hoje = date.today()
    dias_atraso = (hoje - max_data).days
    sla_max_dias = 5

    cumpre_sla = dias_atraso <= sla_max_dias
    cumpre_volume = total_linhas >= 100

    passed = cumpre_sla and cumpre_volume
    severity = AssetCheckSeverity.WARN if not cumpre_sla else AssetCheckSeverity.ERROR

    status_sla = "CUMPRIDO" if cumpre_sla else "ALERTA DE DESATUALIZAÇÃO"
    return AssetCheckResult(
        passed=passed,
        severity=severity,
        metadata={
            "sla_declarado": "D-1 útil (máximo 5 dias corridos)",
            "data_mais_recente": str(max_data),
            "dias_atraso": dias_atraso,
            "total_linhas": total_linhas,
            "volume_minimo_esperado": 100,
        },
        description=(
            f"Dólar atualizado até {max_data} ({dias_atraso}d defasagem, {total_linhas} linhas). "
            f"SLA: {status_sla}."
        ),
    )


@asset_check(
    asset=selic_duckdb,
    description="SLA de atualização e volume mínimo para taxas Selic diárias.",
)
def check_selic_freshness_e_volume(
    context: AssetCheckExecutionContext,
) -> AssetCheckResult:
    """SLA: D+1 útil no SGS (tolerância de até 5 dias corridos para fins de semana e feriados)."""
    if not DB_PADRAO.exists():
        return AssetCheckResult(
            passed=False,
            severity=AssetCheckSeverity.ERROR,
            description=f"Banco de dados DuckDB não encontrado em {DB_PADRAO}",
        )

    con = duckdb.connect(str(DB_PADRAO), read_only=True)
    try:
        resultado = con.execute(
            "select max(data_referencia), count(*) from bronze.selic_taxa"
        ).fetchone()
    finally:
        con.close()

    if not resultado or resultado[0] is None:
        return AssetCheckResult(
            passed=False,
            severity=AssetCheckSeverity.ERROR,
            description="Tabela bronze.selic_taxa está vazia",
        )

    max_data: date = resultado[0]
    total_linhas: int = resultado[1]

    hoje = date.today()
    dias_atraso = (hoje - max_data).days
    sla_max_dias = 5

    cumpre_sla = dias_atraso <= sla_max_dias
    cumpre_volume = total_linhas >= 100

    passed = cumpre_sla and cumpre_volume
    severity = AssetCheckSeverity.WARN if not cumpre_sla else AssetCheckSeverity.ERROR

    status_sla = "CUMPRIDO" if cumpre_sla else "ALERTA DE DESATUALIZAÇÃO"
    return AssetCheckResult(
        passed=passed,
        severity=severity,
        metadata={
            "sla_declarado": "D+1 útil no SGS (máximo 5 dias corridos)",
            "data_mais_recente": str(max_data),
            "dias_atraso": dias_atraso,
            "total_linhas": total_linhas,
            "volume_minimo_esperado": 100,
        },
        description=(
            f"Selic atualizada até {max_data} ({dias_atraso}d defasagem, {total_linhas} linhas). "
            f"SLA: {status_sla}."
        ),
    )


@asset_check(
    asset=AssetKey(["silver", "int_macroeconomia__mensal"]),
    description="SLA de consumo e profundidade histórica para a série macroeconômica consolidada.",
)
def check_macroeconomia_mensal_freshness(
    context: AssetCheckExecutionContext,
) -> AssetCheckResult:
    """SLA: Mensal (defasagem máxima de 45 dias para fechamento e publicação de indicadores)."""
    if not DB_PADRAO.exists():
        return AssetCheckResult(
            passed=False,
            severity=AssetCheckSeverity.ERROR,
            description=f"Banco de dados DuckDB não encontrado em {DB_PADRAO}",
        )

    con = duckdb.connect(str(DB_PADRAO), read_only=True)
    try:
        resultado = con.execute(
            "select max(mes_referencia), count(*) from silver.int_macroeconomia__mensal"
        ).fetchone()
    finally:
        con.close()

    if not resultado or resultado[0] is None:
        return AssetCheckResult(
            passed=False,
            severity=AssetCheckSeverity.ERROR,
            description="Tabela silver.int_macroeconomia__mensal está vazia",
        )

    max_mes: date = resultado[0]
    total_meses: int = resultado[1]

    hoje = date.today()
    dias_atraso = (hoje - max_mes).days
    sla_max_dias = 45

    cumpre_sla = dias_atraso <= sla_max_dias
    cumpre_volume = total_meses >= 12

    passed = cumpre_sla and cumpre_volume
    severity = AssetCheckSeverity.WARN if not cumpre_sla else AssetCheckSeverity.ERROR

    status_sla = "CUMPRIDO" if cumpre_sla else "ALERTA DE DESATUALIZAÇÃO"
    return AssetCheckResult(
        passed=passed,
        severity=severity,
        metadata={
            "sla_declarado": "Mensal (máximo 45 dias após início do mês)",
            "mes_mais_recente": str(max_mes),
            "dias_atraso": dias_atraso,
            "total_meses": total_meses,
            "minimo_meses_requerido": 12,
        },
        description=(
            f"Macroeconomia até {max_mes} ({dias_atraso}d defasagem, {total_meses} meses). "
            f"SLA: {status_sla}."
        ),
    )
