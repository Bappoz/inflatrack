"""popular_banco_job: cada job de fonte vira um run separado; uma falha não derruba as outras."""

from __future__ import annotations

from datetime import UTC, datetime

from dagster import DagsterRunStatus

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
    """Registra em SUBMETIDOS o que foi pedido e devolve o status combinado por job."""

    falham: list[str] = []

    def submeter(self, job: str, tags: dict[str, str]) -> str:
        SUBMETIDOS.append((job, tags))
        return f"run-{job}"

    def status(self, run_id: str) -> DagsterRunStatus:
        job = run_id.removeprefix("run-")
        return DagsterRunStatus.FAILURE if job in self.falham else DagsterRunStatus.SUCCESS


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


def test_definicoes_registram_o_job_com_o_disparador_real() -> None:
    from orchestration.definitions import defs

    repositorio = defs.get_repository_def()
    assert repositorio.has_job("popular_banco_job")
    assert "disparador" in defs.resources
