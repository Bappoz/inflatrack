from datetime import date, datetime

from dagster import build_schedule_context, instance_for_test

from orchestration.definitions import defs
from orchestration.partitions import janela_de_releitura, segmentos_ipca
from orchestration.schedules import SCHEDULES


def test_definicoes_carregam_sem_erro():
    repositorio = defs.get_repository_def()
    assert {"ipca", "dolar", "commodities_duckdb", "clima_duckdb"} <= {
        chave.to_user_string() for chave in repositorio.asset_graph.get_all_asset_keys()
    }


def test_segmentos_ipca_respeitam_troca_de_agregado():
    assert list(segmentos_ipca(date(2011, 11, 1), date(2020, 2, 1))) == [
        (2938, date(2011, 11, 1), date(2011, 12, 1)),
        (1419, date(2012, 1, 1), date(2019, 12, 1)),
        (7060, date(2020, 1, 1), date(2020, 2, 1)),
    ]


def test_segmentos_ipca_dentro_de_um_agregado():
    assert list(segmentos_ipca(date(2026, 5, 1), date(2026, 7, 1))) == [
        (7060, date(2026, 5, 1), date(2026, 7, 1)),
    ]


def test_janela_de_releitura_volta_tres_meses_e_atravessa_o_ano():
    assert janela_de_releitura(date(2027, 2, 10)) == (
        "2027-01-01",
        ["2026-12-01", "2026-11-01", "2026-10-01"],
    )


def _pedidos_do_agendamento_do_ipca(dia: int) -> list:
    (agendamento,) = [item for item in SCHEDULES if item.name == "ipca_job_mensal"]
    # O contexto do agendamento exige instância persistente; a efêmera é recusada.
    with instance_for_test() as instancia:
        contexto = build_schedule_context(
            instance=instancia,
            repository_def=defs.get_repository_def(),
            scheduled_execution_time=datetime(2026, 10, dia, 10, 0),
        )
        return agendamento.evaluate_tick(contexto).run_requests


def test_agendamento_do_ipca_pede_o_mes_novo_e_rele_os_tres_anteriores():
    """Política de dado atrasado: sem reler, uma revisão do IBGE nunca seria vista."""
    pedidos = _pedidos_do_agendamento_do_ipca(dia=9)

    assert [pedido.partition_key for pedido in pedidos] == [
        "2026-09-01",
        "2026-08-01",
        "2026-07-01",
        "2026-06-01",
    ]


def test_agendamento_do_ipca_rele_uma_vez_por_ciclo():
    """O mês novo é tentado de novo a cada dia; a releitura, não.

    O Dagster ignora pedido com `run_key` já vista: a do mês novo muda com o dia, a
    das releituras é a mesma do dia 9 ao 13.
    """
    novo_dia_9, *relidos_dia_9 = _pedidos_do_agendamento_do_ipca(dia=9)
    novo_dia_10, *relidos_dia_10 = _pedidos_do_agendamento_do_ipca(dia=10)

    assert novo_dia_9.run_key != novo_dia_10.run_key
    assert [p.run_key for p in relidos_dia_9] == [p.run_key for p in relidos_dia_10]
    assert len({p.run_key for p in relidos_dia_9}) == 3


def test_grafo_unico_carrega_todos_os_modulos_sem_ativo_duplicado():
    """Cada fonte em seu módulo; o carregamento automático não pode perder nem repetir ativo."""
    from dagster import load_assets_from_package_module

    from orchestration import assets

    ativos = load_assets_from_package_module(assets)
    chaves = [chave.to_user_string() for ativo in ativos for chave in ativo.keys]
    assert len(chaves) == len(set(chaves))
    grupos = {ativo.group_names_by_key[chave] for ativo in ativos for chave in ativo.keys}
    assert {"sidra", "macro", "commodities", "pib", "pib_china", "dieese", "clima"} <= grupos


def test_todo_ativo_que_escreve_no_duckdb_usa_o_pool():
    from orchestration.assets.comum import POOL_DUCKDB

    repositorio = defs.get_repository_def()
    for chave in repositorio.asset_graph.get_all_asset_keys():
        no = repositorio.asset_graph.get(chave)
        if "duckdb" in no.kinds:
            assert no.pools == {POOL_DUCKDB}, chave.to_user_string()
