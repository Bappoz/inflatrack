"""popular_banco_job: a "primeira execução" numa máquina nova.

Não é um job de ativos: IPCA, INPC e número-índice são particionados por mês e o PIB por ano, e o
Dagster recusa partições diferentes num mesmo job de ativos. Em vez disso, uma op por job de fonte
pede ao webserver (API GraphQL) que dispare aquele job como run separado e espera o fim. Os
particionados vão com o intervalo completo nas tags de backfill, que vira um run só por causa do
`BackfillPolicy.single_run()` de cada ativo. Uma fonte que falha deixa o seu run vermelho e não
impede as outras; só a op `resumo` marca o job pai como falho, listando quem falhou.

Silver, Gold e vitrine ficam de fora de propósito: rode o `analitico_job` depois.
"""

import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from dagster import (
    ConfigurableResource,
    DagsterRunStatus,
    Failure,
    In,
    Nothing,
    OpExecutionContext,
    job,
    op,
)
from dagster._core.storage.tags import (
    ASSET_PARTITION_RANGE_END_TAG,
    ASSET_PARTITION_RANGE_START_TAG,
    AUTO_RETRY_RUN_ID_TAG,
    MAX_RETRIES_TAG,
    WILL_RETRY_TAG,
)

from orchestration.partitions import INPC_MENSAL, IPCA_INDICE_MENSAL, IPCA_MENSAL, PIB_ANUAL

NOME_JOB = "popular_banco_job"

# Jobs de fonte e, para os particionados, a definição de partição que dá o intervalo completo.
JOBS_DE_FONTE = {
    "ipca_job": IPCA_MENSAL,
    "inpc_job": INPC_MENSAL,
    "ipca_indice_job": IPCA_INDICE_MENSAL,
    "pib_job": PIB_ANUAL,
    "macro_job": None,
    "commodities_job": None,
    "pib_internacional_job": None,
    "dieese_job": None,
    "clima_job": None,
    "enso_job": None,
    "transacional_job": None,
}

# Quem espera quem. O CDC cria o slot lógico na primeira leitura; disparado junto com a carga
# completa do IPCA (~6 mi de linhas em public.observacao, mais de 2 GB de WAL), o slot fica sem
# leitura além de max_slot_wal_keep_size e o Postgres o invalida (visto num clone limpo em
# 2026-11-08). Esperar não é condicionar: o CDC roda mesmo se uma coleta do SIDRA falhar.
ESPERA = {"transacional_job": ("ipca_job", "inpc_job", "ipca_indice_job")}

TERMINAIS = {DagsterRunStatus.SUCCESS, DagsterRunStatus.FAILURE, DagsterRunStatus.CANCELED}


@dataclass(frozen=True)
class Pedido:
    job: str
    tags: dict[str, str] = field(default_factory=dict)


def pedidos_de_populacao(agora: datetime) -> list[Pedido]:
    """Um pedido por job de fonte; os particionados cobrem da primeira partição até a atual."""
    pedidos = []
    for nome, particoes in JOBS_DE_FONTE.items():
        tags: dict[str, str] = {}
        if particoes is not None:
            chaves = particoes.get_partition_keys(current_time=agora)
            tags = {
                ASSET_PARTITION_RANGE_START_TAG: chaves[0],
                ASSET_PARTITION_RANGE_END_TAG: chaves[-1],
            }
        pedidos.append(Pedido(nome, tags))
    return pedidos


class Disparador(ConfigurableResource):
    """Quem dispara um job e informa o status do run. A implementação real fala com o webserver."""

    def submeter(self, job: str, tags: dict[str, str]) -> str:
        raise NotImplementedError

    def status(self, run_id: str) -> DagsterRunStatus:
        raise NotImplementedError

    def tags(self, run_id: str) -> dict[str, str]:
        raise NotImplementedError


TAGS_DO_RUN = """
query TagsDoRun($runId: ID!) {
  runOrError(runId: $runId) {
    __typename
    ... on Run { tags { key value } }
    ... on PythonError { message }
    ... on RunNotFoundError { message }
  }
}
"""


class DisparadorGraphQL(Disparador):
    """Dispara pelo webserver do `dagster dev` (porta DAGSTER_PORT, como em `just orquestrador`)."""

    host: str = "localhost"
    porta: int = int(os.environ.get("DAGSTER_PORT", "3002"))

    def _cliente(self):
        from dagster_graphql import DagsterGraphQLClient

        return DagsterGraphQLClient(self.host, port_number=self.porta)

    def submeter(self, job: str, tags: dict[str, str]) -> str:
        return self._cliente().submit_job_execution(job, tags=tags)

    def status(self, run_id: str) -> DagsterRunStatus:
        return self._cliente().get_run_status(run_id)

    def tags(self, run_id: str) -> dict[str, str]:
        from dagster_graphql import DagsterGraphQLClientError

        resposta = self._cliente()._execute(TAGS_DO_RUN, {"runId": run_id})["runOrError"]
        if resposta["__typename"] != "Run":
            raise DagsterGraphQLClientError(resposta["__typename"], resposta.get("message"))
        return {tag["key"]: tag["value"] for tag in resposta["tags"]}


INTERVALO_ESPERA_S = 15
# O daemon cria o run novo poucos segundos depois da falha; passou disso, ele não vem mais.
ESPERA_MAX_RETRY_S = 300


def _run_refeito(disparador: Disparador, run_id: str) -> str | None:
    """O run que o Dagster lançou para refazer `run_id` (processo morto), ou None se não houver.

    A tag `dagster/will_retry` sai junto com a falha; o id do run novo, quando o daemon o cria.
    """
    tags = disparador.tags(run_id)
    if tags.get(WILL_RETRY_TAG) != "true":
        return None
    esperado = 0
    while AUTO_RETRY_RUN_ID_TAG not in tags and esperado < ESPERA_MAX_RETRY_S:
        time.sleep(INTERVALO_ESPERA_S)
        esperado += INTERVALO_ESPERA_S
        tags = disparador.tags(run_id)
    return tags.get(AUTO_RETRY_RUN_ID_TAG)


def _op_de_fonte(pedido: Pedido):
    # Entradas `Nothing` só ordenam: a op recebe o fim das anteriores, não o status delas.
    @op(
        name=f"popular_{pedido.job}",
        required_resource_keys={"disparador"},
        ins={f"apos_{job}": In(Nothing) for job in ESPERA.get(pedido.job, ())},
    )
    def _popular(context: OpExecutionContext) -> str:
        disparador: Disparador = context.resources.disparador
        try:
            run_id = disparador.submeter(pedido.job, pedido.tags)
        except Exception as erro:  # noqa: BLE001 — a falha de uma fonte não derruba as outras.
            context.log.error("%s: não foi possível disparar: %s", pedido.job, erro)
            return "NAO_DISPARADO"
        context.log.info("%s: run %s %s", pedido.job, run_id, pedido.tags or "")
        while True:
            status = disparador.status(run_id)
            while status not in TERMINAIS:
                time.sleep(INTERVALO_ESPERA_S)
                status = disparador.status(run_id)
            refeito = None
            if status == DagsterRunStatus.FAILURE:
                refeito = _run_refeito(disparador, run_id)
            if refeito is None:
                break
            context.log.warning(
                "%s: run %s falhou; o Dagster o refaz em %s", pedido.job, run_id, refeito
            )
            run_id = refeito
        context.log.info("%s: %s", pedido.job, status.value)
        return status.value

    return _popular


PEDIDOS = pedidos_de_populacao(datetime.now(UTC))
OPS_DE_FONTE = {pedido.job: _op_de_fonte(pedido) for pedido in PEDIDOS}


@op(ins={nome: In(str) for nome in OPS_DE_FONTE})
def resumo(context: OpExecutionContext, **status_por_job: str) -> Nothing:
    falhas = {nome: status for nome, status in status_por_job.items() if status != "SUCCESS"}
    for nome, status in sorted(status_por_job.items()):
        context.log.info("%s: %s", nome, status)
    if falhas:
        raise Failure(
            "falharam: "
            + ", ".join(f"{nome} ({status})" for nome, status in sorted(falhas.items()))
        )


@job(
    name=NOME_JOB,
    description=(
        "Primeira execução numa máquina nova: dispara cada job de fonte como run separado "
        "(os particionados com o histórico completo) e espera todos. Uma fonte que falha não "
        "impede as outras. Não roda Silver/Gold: rode o analitico_job depois."
    ),
    # Refazer este run dispararia de novo as fontes que ainda estão rodando; as fontes,
    # sim, são refeitas pelo run_retries do dagster.yaml, e a op segue o run novo.
    tags={MAX_RETRIES_TAG: "0"},
)
def popular_banco_job():
    status = {}
    # JOBS_DE_FONTE lista o SIDRA antes do CDC, então quem é esperado já tem saída aqui.
    for nome, op_fonte in OPS_DE_FONTE.items():
        status[nome] = op_fonte(**{f"apos_{job}": status[job] for job in ESPERA.get(nome, ())})
    resumo(**status)
