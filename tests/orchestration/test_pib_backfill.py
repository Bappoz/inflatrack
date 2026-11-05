"""Nível 4 no PIB: partição anual, backfill numa execução só, agendamento e retry com 503."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from dagster import (
    RetryPolicy,
    asset,
    build_schedule_context,
    instance_for_test,
    materialize,
)
from dagster._core.storage.tags import (
    ASSET_PARTITION_RANGE_END_TAG,
    ASSET_PARTITION_RANGE_START_TAG,
)

from inflatrack.bronze import pib as bronze_pib
from inflatrack.common import bronze
from orchestration.assets import pib
from orchestration.assets.comum import RETRY_REDE, executar
from orchestration.partitions import PIB_ANUAL
from orchestration.schedules import agendamento_pib

FIXTURES = Path(__file__).parent.parent / "fixtures" / "pib"


def test_particao_anual_vai_de_1996_ate_o_ano_corrente() -> None:
    chaves = PIB_ANUAL.get_partition_keys(current_time=datetime(2026, 10, 30, tzinfo=UTC))
    assert chaves[0] == "1996"
    assert chaves[-1] == "2026"  # ano corrente, ainda incompleto, também é partição
    assert len(chaves) == 31


def test_backfill_de_varios_anos_vira_uma_execucao_com_de_e_ate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uma chamada para o intervalo inteiro. O ano corrente ainda sem trimestre publicado
    (fora de `Gravacao.anos`) fica pendente, não materializado."""
    chamadas: list[tuple[int, int]] = []

    def coletar(destino: Path, de: int, ate: int) -> bronze_pib.Gravacao:
        chamadas.append((de, ate))
        return bronze_pib.Gravacao(1, 23, 23, anos=(2025,))

    monkeypatch.setattr(pib.bronze_pib, "coletar", coletar)
    with instance_for_test() as instancia:
        resultado = materialize(
            [pib.pib_parquet],
            instance=instancia,
            tags={ASSET_PARTITION_RANGE_START_TAG: "2025", ASSET_PARTITION_RANGE_END_TAG: "2026"},
        )
        materializadas = instancia.get_materialized_partitions(pib.pib_parquet.key)

    assert resultado.success
    assert chamadas == [(2025, 2026)]
    assert materializadas == {"2025"}


def test_agendamento_rele_o_ano_corrente_e_o_anterior() -> None:
    contexto = build_schedule_context(scheduled_execution_time=datetime(2026, 9, 3, 9, tzinfo=UTC))
    pedidos = list(agendamento_pib(contexto))

    assert [pedido.partition_key for pedido in pedidos] == ["2025", "2026"]
    assert len({pedido.run_key for pedido in pedidos}) == 2


@pytest.fixture
def sidra_que_cai_uma_vez(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """SIDRA falso: o 1º pedido de metadados devolve 503; depois, as respostas reais gravadas."""
    pedidos: list[str] = []
    metadados = (FIXTURES / "1846-metadados.json").read_text(encoding="utf-8")
    valores_2026 = (FIXTURES / "1846-2026.json").read_text(encoding="utf-8")

    def responder(requisicao: httpx.Request) -> httpx.Response:
        pedidos.append(str(requisicao.url))
        if "metadados" in requisicao.url.path:
            if sum("metadados" in pedido for pedido in pedidos) == 1:
                return httpx.Response(503, text="Service Unavailable")
            return httpx.Response(200, text=metadados)
        return httpx.Response(200, text=valores_2026)

    cliente_real = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda *a, **k: cliente_real(transport=httpx.MockTransport(responder))
    )

    class AgoraFixo(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 13, 12, tzinfo=UTC)

    monkeypatch.setattr(bronze_pib, "datetime", AgoraFixo)
    return pedidos


def test_dagster_tenta_de_novo_quando_o_sidra_devolve_503(
    tmp_path: Path, sidra_que_cai_uma_vez: list[str]
) -> None:
    """Caminho real: o ingestor captura o 503 e sai com 1, o `executar` vira Failure e a
    política de retry (a do projeto, sem a espera de 30 s) roda o ativo de novo."""

    @asset(retry_policy=RetryPolicy(max_retries=RETRY_REDE.max_retries, delay=0))
    def pib_2026(context) -> None:
        executar(
            context,
            bronze_pib.main,
            "--parquet-dir", str(tmp_path / "pib"),
            "coletar", "--de", "2026", "--ate", "2026",
        )  # fmt: skip

    with instance_for_test() as instancia:
        resultado = materialize([pib_2026], instance=instancia, raise_on_error=False)
        eventos = resultado.all_events

    tentativas = [e for e in eventos if e.event_type_value == "STEP_UP_FOR_RETRY"]
    assert resultado.success
    assert len(tentativas) == 1
    assert sum("metadados" in pedido for pedido in sidra_que_cai_uma_vez) == 2
    assert bronze.ler(tmp_path / "pib", "valor").num_rows == 46  # 2 trimestres x 23 setores
    # Só as duas tabelas Delta: nada de data/raw/ nem Parquet por ano (fim do caminho antigo).
    assert sorted(p.name for p in (tmp_path / "pib").iterdir()) == ["resposta", "valor"]
    assert not (tmp_path / "raw").exists()


def test_reprocessar_o_mesmo_ano_nao_duplica_a_bronze(
    tmp_path: Path, sidra_que_cai_uma_vez: list[str]
) -> None:
    argv = ["--parquet-dir", str(tmp_path / "pib"), "coletar", "--de", "2026", "--ate", "2026"]

    assert bronze_pib.main(argv) == 1  # primeira chamada: SIDRA fora do ar
    assert bronze_pib.main(argv) == 0
    assert bronze_pib.main(argv) == 0  # backfill do mesmo ano, sem revisão nova

    assert bronze.ler(tmp_path / "pib", "valor").num_rows == 46
