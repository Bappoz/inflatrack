"""Jobs e agendamentos, um por grupo de ativos (cadências de docs/pipeline/orquestracao.md).

Os agendamentos nascem desligados: ligue na interface (Automation) para não gastar a
cota da Alpha Vantage nem bater nas APIs só por abrir o `dagster dev`.
"""

from __future__ import annotations

from dagster import (
    AssetKey,
    AssetSelection,
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
pib_job = define_asset_job("pib_job", AssetSelection.groups("pib"))
pib_china_job = define_asset_job("pib_china_job", AssetSelection.groups("pib_china"))
dieese_job = define_asset_job("dieese_job", AssetSelection.groups("dieese"))
clima_job = define_asset_job("clima_job", AssetSelection.groups("clima"))

JOBS = [
    ipca_job,
    inpc_job,
    ipca_indice_job,
    macro_job,
    commodities_job,
    pib_job,
    pib_china_job,
    dieese_job,
    clima_job,
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


SCHEDULES = [
    _agendamento_sidra(ipca_job, "ipca"),
    _agendamento_sidra(inpc_job, "inpc"),
    _agendamento_sidra(ipca_indice_job, "ipca_numero_indice"),
    # Dias úteis, depois do fechamento do BCB.
    ScheduleDefinition(job=macro_job, cron_schedule="0 19 * * 1-5", execution_timezone=FUSO),
    # 1×/dia: 9 requisições cabem na cota de 25/dia.
    ScheduleDefinition(job=commodities_job, cron_schedule="0 8 * * *", execution_timezone=FUSO),
    ScheduleDefinition(job=clima_job, cron_schedule="0 7 * * *", execution_timezone=FUSO),
    agendamento_pib,
    # 1×/mês: o Banco Mundial revisa fora de calendário.
    ScheduleDefinition(job=pib_china_job, cron_schedule="0 9 1 * *", execution_timezone=FUSO),
    ScheduleDefinition(job=dieese_job, cron_schedule="0 9 5 * *", execution_timezone=FUSO),
]
