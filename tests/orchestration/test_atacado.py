"""Job do atacadista: popula o Postgres e não alimenta nada do pipeline analítico (ADR 0004)."""

from dagster import AssetKey

from orchestration.definitions import defs
from orchestration.schedules import SCHEDULES

ATIVO = AssetKey("atacado_postgres")


def test_ativo_grava_so_no_postgres() -> None:
    no = defs.resolve_asset_graph().get(ATIVO)

    assert no.kinds == {"python", "postgres"}
    assert no.group_name == "atacado"


def test_nenhum_ativo_depende_do_atacado() -> None:
    """Se um modelo do dbt ou uma carga no DuckDB dependesse dele, o preço iria para a Bronze."""
    grafo = defs.resolve_asset_graph()

    assert grafo.get(ATIVO).child_keys == set()
    assert grafo.get(ATIVO).parent_keys == set()


def test_atacado_job_roda_so_o_atacado_e_tem_agendamento() -> None:
    job = defs.resolve_job_def("atacado_job")

    assert job.asset_layer.executable_asset_keys == {ATIVO}
    assert "atacado_job" in {agendamento.job_name for agendamento in SCHEDULES}


def test_analitico_job_nao_roda_o_atacado() -> None:
    job = defs.resolve_job_def("analitico_job")

    assert ATIVO not in job.asset_layer.executable_asset_keys


def test_ativo_chama_o_importador_com_a_tabela_de_exemplo(monkeypatch) -> None:
    from dagster import materialize

    from inflatrack.atacado import importar_tabela
    from orchestration.assets import atacado

    chamadas = []
    monkeypatch.setattr(importar_tabela, "main", lambda argv: chamadas.append(argv) or 0)

    assert materialize([atacado.atacado_postgres]).success
    assert chamadas == [list(atacado.ARGUMENTOS)]
    assert "--ficticio" in atacado.ARGUMENTOS
