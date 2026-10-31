from datetime import date

import psycopg
import pytest

from inflatrack import ingest_pib
from inflatrack.bronze import ipca


def test_ingest_desiste_rapido_sem_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem connect_timeout, cada tentativa ficava ~4 min pendurada no Windows."""
    chamadas = []

    def conectar_falhando(*args, **kwargs):
        chamadas.append(kwargs)
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(ipca.psycopg, "connect", conectar_falhando)

    codigo = ipca.main(["coletar", "--agregado", "7060", "--de", "2026-01", "--ate", "2026-01"])

    assert codigo == 1
    assert 0 < chamadas[0]["connect_timeout"] <= 10


class _ConexaoFalsa:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self) -> None:
        pass


def test_ingest_falha_em_mes_nao_publicado(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """O SIDRA responde 200 com lista vazia para mês ainda não divulgado.

    Tratar isso como sucesso fazia o Dagster marcar a partição como materializada, e o
    agendamento pulava os dias seguintes: o mês nunca era carregado.
    """
    monkeypatch.setattr(ipca.psycopg, "connect", lambda *a, **k: _ConexaoFalsa())
    sem_cesta = ipca.sidra.Resposta("https://sidra.invalid/m", 200, "application/json", "{}")
    monkeypatch.setattr(ipca.sidra, "buscar_metadados_resposta", lambda cliente, ag: sem_cesta)
    vazia = ipca.sidra.Resposta("https://sidra.invalid", 200, "application/json", "[]")
    monkeypatch.setattr(ipca.sidra, "buscar_resposta", lambda *a, **k: vazia)

    bronze = tmp_path / "bronze"
    codigo = ipca.main(
        ["--parquet-dir", str(bronze), "coletar"]
        + ["--agregado", "1737", "--de", "2026-10", "--ate", "2026-10"]
    )

    assert codigo == 1
    assert not (bronze / "observacao").exists()  # mês vazio não entra na Bronze


def test_ingest_pib_vai_ate_o_ano_corrente_por_padrao(monkeypatch: pytest.MonkeyPatch) -> None:
    """O padrão era 2026 fixo: em 2027 o job seguia com sucesso sem baixar o ano novo."""

    class Em2027(date):
        @classmethod
        def today(cls) -> date:
            return date(2027, 3, 15)

    recebido = {}
    monkeypatch.setattr(ingest_pib, "date", Em2027, raising=False)
    monkeypatch.setattr(ingest_pib, "executar", lambda args: recebido.update(vars(args)) or 0)

    assert ingest_pib.main([]) == 0
    assert recebido["ate"] == 2027
