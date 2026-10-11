from datetime import date

from orchestration.definitions import defs
from orchestration.partitions import segmentos_ipca


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
