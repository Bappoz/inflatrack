from datetime import date

import psycopg
import pytest

from inflatrack import ingest, ingest_pib


def test_ingest_desiste_rapido_sem_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem connect_timeout, cada tentativa ficava ~4 min pendurada no Windows."""
    chamadas = []

    def conectar_falhando(*args, **kwargs):
        chamadas.append(kwargs)
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(ingest.psycopg, "connect", conectar_falhando)

    codigo = ingest.main(["--agregado", "7060", "--de", "2026-01", "--ate", "2026-01"])

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
    monkeypatch.setattr(ingest.psycopg, "connect", lambda *a, **k: _ConexaoFalsa())
    monkeypatch.setattr(ingest.sidra, "buscar_metadados", lambda cliente, agregado: {})
    vazia = ingest.sidra.Resposta("https://sidra.invalid", 200, "application/json", "[]")
    monkeypatch.setattr(ingest.sidra, "buscar_resposta", lambda *a, **k: vazia)

    raw, bronze = tmp_path / "raw", tmp_path / "bronze"
    codigo = ingest.main(
        ["--agregado", "1737", "--de", "2026-10", "--ate", "2026-10"]
        + ["--raw-dir", str(raw), "--parquet-dir", str(bronze)]
    )

    assert codigo == 1
    assert not raw.exists()  # Raw vazio não é gravado
    assert not bronze.exists()  # nem a Bronze


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
