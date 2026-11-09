"""Jobs e schedules de fontes e publicação do dashboard.

Só IPCA/INPC e número-índice são ativados por padrão: são as séries públicas consumidas pelo
dashboard. As demais fontes externas continuam opt-in para proteger suas cotas.
"""

from __future__ import annotations

from dagster import (
    AssetKey,
    AssetSelection,
    DefaultScheduleStatus,
    JobDefinition,
    RunRequest,
    ScheduleDefinition,
    ScheduleEvaluationContext,
    define_asset_job,
    schedule,
)

from orchestration.partitions import ANOS_RELIDOS_PIB, janela_de_releitura

FUSO = "America/Sao_Paulo"

ipca_job = define_asset_job("ipca_job", AssetSelection.assets("ipca"))
inpc_job = define_asset_job("inpc_job", AssetSelection.assets("inpc"))
ipca_indice_job = define_asset_job("ipca_indice_job", AssetSelection.assets("ipca_numero_indice"))
macro_job = define_asset_job("macro_job", AssetSelection.groups("macro"))
commodities_job = define_asset_job("commodities_job", AssetSelection.groups("commodities"))
# Só a coleta: a carga no DuckDB vai no analitico_job (ver CARGAS_SEM_JOB_PROPRIO).
pib_job = define_asset_job("pib_job", AssetSelection.assets("pib_parquet"))
pib_internacional_job = define_asset_job(
    "pib_internacional_job", AssetSelection.groups("pib_internacional")
)
dieese_job = define_asset_job("dieese_job", AssetSelection.groups("dieese"))
clima_job = define_asset_job("clima_job", AssetSelection.groups("clima"))
transacional_job = define_asset_job("transacional_job", AssetSelection.groups("transacional"))

# As cargas do IPCA e do PIB no DuckDB não são particionadas (espelham o Delta inteiro) e
# dependem de coletas particionadas que só materializam o que a fonte publicou, sem `Output`
# (`output_required=False`). No mesmo run da coleta, o Dagster pularia a carga; por isso elas
# entram no analitico_job, que roda depois das fontes.
CARGAS_SEM_JOB_PROPRIO = AssetSelection.assets("ipca_duckdb", "ipca_metadados_duckdb", "pib_duckdb")

# Cargas do IPCA e do PIB, Silver, Gold e a cópia para o Postgres (serie), na ordem do grafo,
# depois que as fontes do dia já rodaram. Quem lê o painel vê o dado do dia seguinte de manhã.
analitico_job = define_asset_job(
    "analitico_job",
    AssetSelection.groups("silver", "gold", "vitrine") | CARGAS_SEM_JOB_PROPRIO,
)

dashboard_job = define_asset_job(
    "dashboard_job",
    AssetSelection.assets(
        AssetKey("ipca_duckdb"),
        AssetKey("ipca_metadados_duckdb"),
        AssetKey(["silver", "seed_agregado_sidra"]),
        AssetKey(["silver", "seed_localidade_ibge"]),
        AssetKey(["silver", "seed_variavel_sidra"]),
        AssetKey(["silver", "stg_ipca__metadados"]),
        AssetKey(["silver", "stg_ipca__observacao"]),
        AssetKey(["silver", "int_ipca__mensal"]),
        AssetKey(["gold", "dim_calendario"]),
        AssetKey(["gold", "dim_localidade"]),
        AssetKey(["gold", "dim_cesta_ipca_scd2"]),
        AssetKey(["gold", "fct_inflacao_mensal"]),
        AssetKey("dashboard_serie_postgres"),
    ),
)

JOBS = [
    ipca_job,
    inpc_job,
    ipca_indice_job,
    macro_job,
    commodities_job,
    pib_job,
    pib_internacional_job,
    dieese_job,
    clima_job,
    transacional_job,
    analitico_job,
    dashboard_job,
]


def _agendamento_sidra(job: JobDefinition, ativo: str):
    """Dias 9 a 13, 1×/dia: carrega o mês novo e relê os meses que podem ter sido revisados.

    O IBGE não divulga sempre no mesmo dia: rodar a janela inteira e pular quando já
    carregou é mais barato que acertar a data. A releitura dos meses anteriores (ver
    `janela_de_releitura`) acontece uma vez por ciclo, porque a `run_key` não muda de um
    dia para o outro e o Dagster ignora pedido repetido.
    """

    @schedule(
        name=f"{job.name}_mensal",
        job=job,
        cron_schedule="0 10 9-13 * *",
        execution_timezone=FUSO,
        default_status=DefaultScheduleStatus.RUNNING,
    )
    def _agendamento(context: ScheduleEvaluationContext):
        execucao = context.scheduled_execution_time
        novo, relidos = janela_de_releitura(execucao.date())
        if novo not in context.instance.get_materialized_partitions(AssetKey(ativo)):
            yield RunRequest(run_key=f"{ativo}-{execucao:%Y-%m-%d}", partition_key=novo)
        for mes in relidos:
            yield RunRequest(run_key=f"{ativo}-releitura-{novo}-{mes}", partition_key=mes)

    return _agendamento


@schedule(
    name="pib_job_divulgacao",
    job=pib_job,
    # Diário só nos meses de divulgação das contas trimestrais.
    cron_schedule="0 9 * 3,6,9,12 *",
    execution_timezone=FUSO,
)
def agendamento_pib(context: ScheduleEvaluationContext):
    """Relê o ano corrente e o anterior: a divulgação nova revisa trimestres já publicados."""
    execucao = context.scheduled_execution_time
    for ano in range(execucao.year - ANOS_RELIDOS_PIB, execucao.year + 1):
        yield RunRequest(run_key=f"pib-{ano}-{execucao:%Y-%m-%d}", partition_key=str(ano))


# Ordem do dia (fuso de São Paulo): clima 7h, commodities 8h, 9h para PIB (meses de
# divulgação), PIB internacional (dia 1) e DIEESE (dia 5), IPCA 10h (dias 9 a 13),
# Dólar/Selic 19h (dias úteis), transacional de hora em hora; o analitico_job fecha o dia
# às 20h30. Um escritor por vez no DuckDB (pool).
SCHEDULES = [
    _agendamento_sidra(ipca_job, "ipca"),
    _agendamento_sidra(inpc_job, "inpc"),
    _agendamento_sidra(ipca_indice_job, "ipca_numero_indice"),
    # Dias úteis, depois do fechamento do BCB.
    ScheduleDefinition(job=macro_job, cron_schedule="0 19 * * 1-5", execution_timezone=FUSO),
    # 1×/dia: 9 requisições cabem na cota de 25/dia.
    ScheduleDefinition(job=commodities_job, cron_schedule="0 8 * * *", execution_timezone=FUSO),
    ScheduleDefinition(job=clima_job, cron_schedule="0 7 * * *", execution_timezone=FUSO),
    # De hora em hora: cada leitura só traz o que mudou, e o WAL segura o resto entre as leituras.
    ScheduleDefinition(job=transacional_job, cron_schedule="0 * * * *", execution_timezone=FUSO),
    agendamento_pib,
    # 1×/mês: o Banco Mundial revisa fora de calendário.
    ScheduleDefinition(
        job=pib_internacional_job, cron_schedule="0 9 1 * *", execution_timezone=FUSO
    ),
    ScheduleDefinition(job=dieese_job, cron_schedule="0 9 5 * *", execution_timezone=FUSO),
    ScheduleDefinition(
        job=dashboard_job,
        cron_schedule="30 20 * * *",
        execution_timezone=FUSO,
        default_status=DefaultScheduleStatus.RUNNING,
    ),
]
