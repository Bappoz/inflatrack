"""Topologia dos ativos do IPCA e do banco do lojista, até a vitrine `serie` no Postgres."""

from dagster import AssetKey

from inflatrack.reverse_etl import exportar_serie
from orchestration.definitions import defs
from orchestration.schedules import SCHEDULES

GRAFO = defs.get_repository_def().asset_graph


def _depende_de(ativo: AssetKey, origem: AssetKey) -> bool:
    return origem in GRAFO.get(ativo).parent_keys


def test_carga_do_ipca_vem_depois_das_tres_coletas() -> None:
    for destino in ("ipca_duckdb", "ipca_metadados_duckdb"):
        for coleta in ("ipca", "inpc", "ipca_numero_indice"):
            assert _depende_de(AssetKey(destino), AssetKey(coleta))


def test_silver_do_ipca_roda_depois_do_loader() -> None:
    assert _depende_de(AssetKey(["silver", "stg_ipca__observacao"]), AssetKey("ipca_duckdb"))
    assert _depende_de(
        AssetKey(["silver", "stg_ipca__metadados"]), AssetKey("ipca_metadados_duckdb")
    )


def test_silver_do_lojista_roda_depois_do_cdc() -> None:
    assert _depende_de(AssetKey("transacional_duckdb"), AssetKey("transacional_delta"))
    assert _depende_de(
        AssetKey(["silver", "stg_transacional__mudanca"]), AssetKey("transacional_duckdb")
    )


def test_gold_vem_da_silver_e_o_lojista_compara_com_a_fato_oficial() -> None:
    assert _depende_de(
        AssetKey(["gold", "fct_reajuste_lojista"]), AssetKey(["gold", "fct_inflacao_mensal"])
    )
    # O caminho inverso quebraria o isolamento: dado do lojista nunca entra na fato oficial.
    assert not _depende_de(
        AssetKey(["gold", "fct_inflacao_mensal"]), AssetKey(["gold", "fct_reajuste_lojista"])
    )


def test_vitrine_espera_todas_as_tabelas_copiadas() -> None:
    assert "fct_inflacao_mensal" in exportar_serie.TABELAS
    for tabela in exportar_serie.TABELAS:
        assert _depende_de(AssetKey("serie_postgres"), AssetKey(["gold", tabela]))


def test_todo_ativo_que_abre_o_duckdb_entra_no_pool_de_escrita() -> None:
    for chave in ("ipca_duckdb", "transacional_duckdb", "serie_postgres"):
        passo = GRAFO.get(AssetKey(chave)).assets_def.node_def
        assert passo.pool == "duckdb_writer", chave


def test_cdc_tem_agendamento() -> None:
    assert "transacional_job_schedule" in {agendamento.name for agendamento in SCHEDULES}
