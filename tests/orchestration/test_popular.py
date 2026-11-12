"""popular_banco_job: cada job de fonte vira um run separado; uma falha não derruba as outras."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml
from dagster import DagsterRunStatus
from dagster._core.storage.tags import AUTO_RETRY_RUN_ID_TAG, MAX_RETRIES_TAG, WILL_RETRY_TAG

from orchestration.popular import (
    Disparador,
    pedidos_de_populacao,
    popular_banco_job,
)
from orchestration.schedules import JOBS

FONTES = {
    "ipca_job",
    "inpc_job",
    "ipca_indice_job",
    "pib_job",
    "macro_job",
    "commodities_job",
    "pib_internacional_job",
    "dieese_job",
    "clima_job",
    "enso_job",
    "transacional_job",
}


def test_pedidos_cobrem_todas_as_fontes_e_nada_mais() -> None:
    pedidos = pedidos_de_populacao(datetime(2026, 11, 5, tzinfo=UTC))
    assert {pedido.job for pedido in pedidos} == FONTES
    # Todo job de fonte registrado no Dagster entra; o analítico e o próprio popular ficam fora.
    assert {job.name for job in JOBS} - {"analitico_job", "popular_banco_job"} == FONTES


def test_particionados_pedem_o_intervalo_completo_e_os_demais_nao_levam_tags() -> None:
    por_job = {
        pedido.job: pedido for pedido in pedidos_de_populacao(datetime(2026, 11, 5, tzinfo=UTC))
    }
    assert por_job["ipca_job"].tags == {
        "dagster/asset_partition_range_start": "2006-07-01",
        # Em 5/11 a partição de novembro ainda não existe: o mês só vira partição quando fecha.
        "dagster/asset_partition_range_end": "2026-10-01",
    }
    assert por_job["ipca_indice_job"].tags["dagster/asset_partition_range_start"] == "1979-12-01"
    assert por_job["inpc_job"].tags["dagster/asset_partition_range_start"] == "2020-01-01"
    assert por_job["pib_job"].tags == {
        "dagster/asset_partition_range_start": "1996",
        "dagster/asset_partition_range_end": "2026",
    }
    assert por_job["macro_job"].tags == {}


SUBMETIDOS: list[tuple[str, dict[str, str]]] = []


class DisparadorFalso(Disparador):
    """Registra em SUBMETIDOS o que foi pedido e devolve o status combinado por job.

    `refeitos`: o 1º run do job morre (processo encerrado) e o Dagster o refaz num run novo,
    que termina com sucesso, a menos que o job também esteja em `falham`.
    """

    falham: list[str] = []
    refeitos: list[str] = []

    def submeter(self, job: str, tags: dict[str, str]) -> str:
        SUBMETIDOS.append((job, tags))
        return f"run-{job}"

    def status(self, run_id: str) -> DagsterRunStatus:
        job = run_id.removeprefix("run-").removesuffix("-retry")
        if job in self.refeitos and not run_id.endswith("-retry"):
            return DagsterRunStatus.FAILURE
        return DagsterRunStatus.FAILURE if job in self.falham else DagsterRunStatus.SUCCESS

    def tags(self, run_id: str) -> dict[str, str]:
        job = run_id.removeprefix("run-")
        if job in self.refeitos:
            return {WILL_RETRY_TAG: "true", AUTO_RETRY_RUN_ID_TAG: f"{run_id}-retry"}
        return {WILL_RETRY_TAG: "false"}


def test_falha_de_uma_fonte_nao_impede_as_outras() -> None:
    SUBMETIDOS.clear()
    disparador = DisparadorFalso(falham=["ipca_job"])

    resultado = popular_banco_job.execute_in_process(
        resources={"disparador": disparador}, raise_on_error=False
    )

    assert {job for job, _ in SUBMETIDOS} == FONTES
    assert not resultado.success
    # As ops de fonte terminam bem mesmo quando o run disparado falha; só o resumo acusa.
    assert resultado.is_node_success("popular_ipca_job")
    assert resultado.is_node_success("popular_clima_job")
    assert resultado.is_node_failed("resumo")
    mensagem = resultado.failure_data_for_node("resumo").error.message
    assert "ipca_job" in mensagem
    assert "clima_job" not in mensagem


def test_sem_falhas_o_job_termina_em_sucesso() -> None:
    SUBMETIDOS.clear()
    disparador = DisparadorFalso(falham=[])
    resultado = popular_banco_job.execute_in_process(resources={"disparador": disparador})
    assert resultado.success
    assert len(SUBMETIDOS) == len(FONTES)


def test_run_refeito_pelo_dagster_conta_pelo_resultado_do_run_novo() -> None:
    """O processo de um run morre e o Dagster o refaz: vale o status do run novo."""
    SUBMETIDOS.clear()
    resultado = popular_banco_job.execute_in_process(
        resources={"disparador": DisparadorFalso(refeitos=["ipca_job", "enso_job"])}
    )
    assert resultado.success
    assert resultado.output_for_node("popular_ipca_job") == "SUCCESS"
    # O run novo é do Dagster, não um segundo pedido: cada fonte é submetida uma vez só.
    assert len(SUBMETIDOS) == len(FONTES)


def test_run_refeito_que_falha_de_novo_aparece_no_resumo() -> None:
    SUBMETIDOS.clear()
    resultado = popular_banco_job.execute_in_process(
        resources={"disparador": DisparadorFalso(refeitos=["enso_job"], falham=["enso_job"])},
        raise_on_error=False,
    )
    assert resultado.is_node_failed("resumo")
    assert "enso_job" in resultado.failure_data_for_node("resumo").error.message


def test_popular_banco_job_nao_e_refeito_pelo_dagster() -> None:
    """Refazer o pai dispararia de novo as fontes que ainda estão rodando."""
    assert popular_banco_job.tags[MAX_RETRIES_TAG] == "0"


def test_instancia_refaz_so_runs_cujo_processo_morreu() -> None:
    """O processo de um run ou de um passo morre sem traceback quando o `popular_banco_job`
    sobe as 11 fontes juntas (2026-11-12). Erro de verdade num passo não refaz o run: a cota
    de 25 req./dia das commodities não pode ir embora em retentativas."""
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".dagster" / "dagster.yaml").read_text("utf-8")
    )
    assert config["run_retries"] == {
        "enabled": True,
        "max_retries": 2,
        "retry_on_asset_or_op_failure": False,
    }


def test_definicoes_registram_o_job_com_o_disparador_real() -> None:
    from orchestration.definitions import defs

    repositorio = defs.get_repository_def()
    assert repositorio.has_job("popular_banco_job")
    assert "disparador" in defs.resources


SIDRA = ("ipca_job", "inpc_job", "ipca_indice_job")


def test_cdc_so_e_disparado_depois_das_coletas_do_sidra() -> None:
    """A carga completa do IPCA gera mais de 2 GB de WAL. Com o slot do CDC criado no meio dela
    e sem leitura, o Postgres o invalida (max_slot_wal_keep_size), como num clone limpo em
    2026-11-08. O CDC espera o SIDRA, mesmo quando uma coleta do SIDRA falha."""
    SUBMETIDOS.clear()
    popular_banco_job.execute_in_process(
        resources={"disparador": DisparadorFalso(falham=["inpc_job"])}, raise_on_error=False
    )

    ordem = [job for job, _ in SUBMETIDOS]
    assert "transacional_job" in ordem
    assert all(ordem.index(job) < ordem.index("transacional_job") for job in SIDRA)
    upstream = popular_banco_job.graph.dependency_structure.all_upstream_outputs_from_node(
        "popular_transacional_job"
    )
    assert {saida.node_name for saida in upstream} == {f"popular_{job}" for job in SIDRA}
