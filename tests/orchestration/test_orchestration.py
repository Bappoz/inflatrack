from datetime import date, datetime

from dagster import build_schedule_context, instance_for_test

from orchestration.definitions import defs
from orchestration.partitions import janela_de_releitura, segmentos_ipca
from orchestration.schedules import SCHEDULES


def test_definicoes_carregam_sem_erro():
    repositorio = defs.get_repository_def()
    assert {"ipca", "dolar_duckdb", "selic_duckdb", "commodities_duckdb", "clima_duckdb"} <= {
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
    assert {
        "sidra",
        "macro",
        "commodities",
        "pib",
        "pib_internacional",
        "dieese",
        "clima",
    } <= grupos


def test_todo_ativo_que_escreve_no_duckdb_usa_o_pool():
    from orchestration.assets.comum import POOL_DUCKDB

    repositorio = defs.get_repository_def()
    for chave in repositorio.asset_graph.get_all_asset_keys():
        no = repositorio.asset_graph.get(chave)
        if "duckdb" in no.kinds:
            assert no.pools == {POOL_DUCKDB}, chave.to_user_string()


def test_toda_carga_no_duckdb_roda_por_algum_job_agendado():
    """Uma carga fora de todo job agendado deixa a Gold parada mesmo com a coleta rodando.

    Foi o caso do IPCA: `ipca_job` só coletava, e nada levava o Delta para `bronze.*`.
    """
    agendados = {agendamento.job_name for agendamento in SCHEDULES}
    cobertas = set()
    for job in defs.resolve_all_job_defs():
        if job.name in agendados:
            cobertas |= {c.to_user_string() for c in job.asset_layer.executable_asset_keys}

    grafo = defs.resolve_asset_graph()
    cargas = {
        chave.to_user_string()
        for chave in grafo.get_all_asset_keys()
        if chave.to_user_string().endswith("_duckdb") and "dbt" not in grafo.get(chave).kinds
    }
    assert cargas <= cobertas, cargas - cobertas


def test_analitico_job_carrega_o_ipca_antes_do_dbt():
    job = defs.resolve_job_def("analitico_job")
    selecionadas = {c.to_user_string() for c in job.asset_layer.executable_asset_keys}
    assert {"ipca_duckdb", "ipca_metadados_duckdb", "serie_postgres"} <= selecionadas
    assert "gold/fct_inflacao_mensal" in selecionadas


def test_dependencias_e_configuracao_dolar_e_selic():
    """Valida o grafo de dependências, particionamento e pools de Dólar e Selic."""
    from dagster import AssetKey

    from orchestration.assets.comum import POOL_DUCKDB

    grafo = defs.get_repository_def().asset_graph

    # Dólar
    dolar_p = grafo.get(AssetKey(["dolar_parquet"]))
    dolar_d = grafo.get(AssetKey(["dolar_duckdb"]))
    assert dolar_p.group_name == "macro"
    assert dolar_d.group_name == "macro"
    assert {p.to_user_string() for p in dolar_d.parent_keys} == {"dolar_parquet"}
    assert dolar_d.pools == {POOL_DUCKDB}
    assert "duckdb" in dolar_d.kinds

    # Selic
    selic_p = grafo.get(AssetKey(["selic_parquet"]))
    selic_d = grafo.get(AssetKey(["selic_duckdb"]))
    assert selic_p.group_name == "macro"
    assert selic_d.group_name == "macro"
    assert {p.to_user_string() for p in selic_d.parent_keys} == {"selic_parquet"}
    assert selic_d.pools == {POOL_DUCKDB}
    assert "duckdb" in selic_d.kinds


def test_execucao_assets_dolar_e_selic_com_mock():
    """Valida execução dos assets dolar_duckdb e selic_duckdb chamando os loaders."""
    from unittest.mock import patch

    from dagster import build_asset_context

    from orchestration.assets import dolar as asset_dolar
    from orchestration.assets import selic as asset_selic

    with patch("inflatrack.loaders.load_dolar.main", return_value=0) as mock_dolar_main:
        ctx = build_asset_context()
        asset_dolar.dolar_duckdb(ctx)
        mock_dolar_main.assert_called_once_with([])

    with patch("inflatrack.loaders.load_selic.main", return_value=0) as mock_selic_main:
        ctx = build_asset_context()
        asset_selic.selic_duckdb(ctx)
        mock_selic_main.assert_called_once_with([])


def test_nenhum_job_roda_algo_abaixo_de_um_ativo_de_saida_opcional():
    """Um ativo com `output_required=False` (IPCA, INPC, número-índice e PIB) só emite
    `AssetMaterialization` das partições publicadas, sem `Output`. O Dagster então pula todo
    passo do mesmo run que depende dele. Foi o caso do `pib_duckdb` dentro do `pib_job`:
    `bronze.pib_valor` nunca era criada, e o `dbt build` caía no clone limpo (2026-11-08).
    A carga desses ativos roda em outro job (`analitico_job`)."""
    repositorio = defs.get_repository_def()
    grafo = repositorio.asset_graph
    opcionais = {
        chave
        for chave in grafo.get_all_asset_keys()
        if (no := grafo.get(chave)).is_partitioned
        and not all(saida.is_required for saida in no.assets_def.node_def.output_defs)
    }
    assert {"ipca", "pib_parquet"} <= {chave.to_user_string() for chave in opcionais}

    for job in repositorio.get_all_jobs():
        if job.name.startswith("__") or job.asset_layer is None:
            continue
        selecionados = job.asset_layer.selected_asset_keys
        for chave in selecionados:
            presos = grafo.get(chave).parent_keys & opcionais & selecionados
            assert not presos, f"{job.name}: {chave.to_user_string()} depende de {presos}"
