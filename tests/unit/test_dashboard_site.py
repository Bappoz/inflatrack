"""Dashboard de uma praça montado da `serie` local, para publicar no Supabase."""

from datetime import date
from decimal import Decimal

from psycopg.rows import dict_row

from inflatrack.reverse_etl import publicar_site
from inflatrack.reverse_etl.dashboard_site import load_dashboard_data


class FakeCursor:
    def __init__(self) -> None:
        self.query_index = -1
        self.queries: list[str] = []
        self.params: list[dict[str, object]] = []
        self.rows = [
            [{"mes": date(2026, 9, 1), "ipca_12m_pct": Decimal("4.5"), "inpc_12m_pct": 4.2}],
            [{"setor": "Índice geral", "inflacao_12m_pct": 4.5}],
            [{"localidade": "Brasil", "uf": None, "ipca_12m_pct": 4.5, "inpc_12m_pct": 4.2}],
            [{"codigo_localidade": 1, "nome_localidade": "Brasil", "uf": None}],
            [{"mes_referencia": date(2026, 9, 1), "ipca_12m_pct": 4.5, "inpc_12m_pct": 4.2}],
            [{"mes_numero": 1, "mes": "jan", "indice_geral_pct": 0.4}],
            [{"mes_referencia": date(2026, 9, 1), "poder_compra_100_reais": 46.0}],
        ]

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: str, params: dict[str, object] | None = None) -> None:
        self.queries.append(query)
        if params is not None:
            self.params.append(params)
        if query != "SET TRANSACTION READ ONLY":
            self.query_index += 1

    def fetchone(self) -> dict[str, object]:
        return self.rows[self.query_index][0]

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows[self.query_index]


class FakeConnection:
    def __init__(self) -> None:
        self.fake_cursor = FakeCursor()

    def cursor(self, *, row_factory):
        assert row_factory is dict_row
        return self.fake_cursor


def test_dashboard_le_a_serie_em_transacao_somente_leitura() -> None:
    conexao = FakeConnection()

    dados = load_dashboard_data(conexao, 29, 0)

    assert dados["latest_month"] == date(2026, 9, 1)
    assert dados["kpis"] == {"ipca_12m_pct": Decimal("4.5"), "inpc_12m_pct": 4.2}
    assert dados["location_options"][0]["nome_localidade"] == "Brasil"
    assert {"localidade": 29, "periodo": 0} in conexao.fake_cursor.params
    assert conexao.fake_cursor.queries[0] == "SET TRANSACTION READ ONLY"
    assert all("serie." in query for query in conexao.fake_cursor.queries[1:])


def test_publicacao_guarda_o_historico_inteiro_de_cada_praca_em_json() -> None:
    """Datas viram ISO e Decimal vira float em qualquer nível do dashboard (jsonb)."""
    conexao = FakeConnection()

    dados = publicar_site.dashboard_json(load_dashboard_data(conexao, 1, 0))

    assert dados["latest_month"] == "2026-09-01"
    assert dados["kpis"]["ipca_12m_pct"] == 4.5
    assert dados["history"][0]["mes_referencia"] == "2026-09-01"
    assert conexao.fake_cursor.params[0]["periodo"] == 0
