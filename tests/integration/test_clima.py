"""Testes da camada Bronze em Delta para Dados do Clima (INMET).

Cobre transformação fiel sem valores padrão inventados, checagens de
integridade geográfica e volume, idempotência em Delta e importação do Raw.
"""

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from deltalake import DeltaTable
from inflatrack.load_clima import carregar_bronze_medicoes

from inflatrack import bronze_clima, ingest_clima

FIXTURES = Path(__file__).parent.parent / "fixtures" / "clima"
QUANDO = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
def payload_estacoes() -> list[dict]:
    caminho = FIXTURES / "estacoes.json"
    return json.loads(caminho.read_text(encoding="utf-8"))


def tabela(destino: Path, nome: str) -> list[dict]:
    return DeltaTable(str(destino / nome)).to_pyarrow_table().to_pylist()


def test_transformar_mantem_todas_as_estacoes(payload_estacoes) -> None:
    """Extrai todas as 671 estações retornadas pelo INMET."""
    linhas = bronze_clima.transformar(payload_estacoes)
    assert len(linhas) == 671
    assert linhas[0]["estacao_id"] == "A001"
    assert linhas[0]["nome"] == "BRASILIA"
    assert linhas[0]["estado"] == "DF"


def test_transformar_nao_inventa_valores_padrao() -> None:
    """Campos como tipo e situação não devem receber fallbacks inventados
    (ex.: 'Automatica' / 'Operante').
    """
    payload_com_nulos = [
        {
            "CD_ESTACAO": "TEST01",
            "DC_NOME": "ESTACAO TESTE",
            "SG_ESTADO": "DF",
            "TP_ESTACAO": None,
            "CD_SITUACAO": None,
            "VL_LATITUDE": "-15.78",
            "VL_LONGITUDE": "-47.92",
            "VL_ALTITUDE": "1000",
        }
    ]
    linhas = bronze_clima.transformar(payload_com_nulos)
    assert len(linhas) == 1
    assert linhas[0]["tipo"] is None
    assert linhas[0]["situacao"] is None


def test_transformar_converte_coordenadas_e_altitude() -> None:
    payload = [
        {
            "CD_ESTACAO": "A001",
            "DC_NOME": "BRASILIA",
            "SG_ESTADO": "DF",
            "TP_ESTACAO": "Automatica",
            "VL_LATITUDE": "-15.7894",
            "VL_LONGITUDE": "-47.9258",
            "VL_ALTITUDE": "1159.5",
            "CD_SITUACAO": "Operante",
        }
    ]
    linhas = bronze_clima.transformar(payload)
    assert linhas[0]["latitude"] == pytest.approx(-15.7894)
    assert linhas[0]["longitude"] == pytest.approx(-47.9258)
    assert linhas[0]["altitude_m"] == pytest.approx(1159.5)


def test_checar_valido(payload_estacoes) -> None:
    linhas = bronze_clima.transformar(payload_estacoes)
    bronze_clima.checar(linhas)


def test_checar_rejeita_vazio() -> None:
    with pytest.raises(bronze_clima.ChecagemError, match="vazio"):
        bronze_clima.checar([])


def test_checar_rejeita_duplicados(payload_estacoes) -> None:
    linhas = bronze_clima.transformar(payload_estacoes)
    linhas_com_duplicata = linhas + [linhas[0]]
    with pytest.raises(bronze_clima.ChecagemError, match="duplicados"):
        bronze_clima.checar(linhas_com_duplicata)


def test_checar_rejeita_coordenadas_fora_do_brasil(payload_estacoes) -> None:
    linhas = bronze_clima.transformar(payload_estacoes)
    # Altera uma estação para o Polo Norte
    linhas[0]["latitude"] = 85.0
    with pytest.raises(bronze_clima.ChecagemError, match="latitude inválida"):
        bronze_clima.checar(linhas)


def test_gravar_idempotente(tmp_path: Path, payload_estacoes) -> None:
    destino = tmp_path / "clima"

    # Primeira execução: grava todas as 671 estações
    grav1 = bronze_clima.gravar(destino, payload_estacoes, ingerido_em=QUANDO)
    assert grav1.resposta_nova is True
    assert grav1.linhas_novas == 671
    assert grav1.linhas_lidas == 671

    # Segunda execução (mesma resposta): nenhuma linha nova nem resposta nova
    grav2 = bronze_clima.gravar(destino, payload_estacoes, ingerido_em=QUANDO)
    assert grav2.resposta_nova is False
    assert grav2.linhas_novas == 0
    assert grav2.linhas_lidas == 671

    respostas = tabela(destino, "resposta")
    estacoes = tabela(destino, "estacao")
    assert len(respostas) == 1
    assert len(estacoes) == 671
    assert respostas[0]["_fonte"] == "clima"
    assert estacoes[0]["_id_resposta"] == respostas[0]["id_resposta"]


def test_gravar_atualizacao_estacao(tmp_path: Path, payload_estacoes) -> None:
    """Se o INMET atualizar o cadastro de uma estação (ex: situação Pane -> Operante),
    a nova versão é registrada sem apagar a anterior."""
    destino = tmp_path / "clima"
    bronze_clima.gravar(destino, payload_estacoes, ingerido_em=QUANDO)

    # Simula alteração de situação de uma estação
    payload_atualizado = [dict(item) for item in payload_estacoes]
    payload_atualizado[0]["CD_SITUACAO"] = "Pane"

    quando_depois = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
    grav_upd = bronze_clima.gravar(destino, payload_atualizado, ingerido_em=quando_depois)

    assert grav_upd.resposta_nova is True
    assert grav_upd.linhas_novas == 1

    estacoes = tabela(destino, "estacao")
    eid = payload_estacoes[0]["CD_ESTACAO"]
    versoes = [e for e in estacoes if e["estacao_id"] == eid]
    assert len(versoes) == 2


def test_gravar_medicoes_idempotente_e_preserva_revisao(tmp_path: Path) -> None:
    destino = tmp_path / "clima"
    payload = [
        {
            "CD_ESTACAO": "A001",
            "DT_MEDICAO": "2026-10-01",
            "TEM_MIN": "0.0",
            "TEM_MAX": "20.0",
            "TEM_MED": "10.0",
            "CHUVA": "0.0",
        }
    ]

    primeira = bronze_clima.gravar_medicoes(
        destino,
        payload,
        requisicao="/estacao/diaria/2026-10-01/2026-10-01/A001",
        ingerido_em=QUANDO,
    )
    repetida = bronze_clima.gravar_medicoes(
        destino,
        payload,
        requisicao="/estacao/diaria/2026-10-01/2026-10-01/A001",
        ingerido_em=datetime(2026, 10, 12, 10, 0, tzinfo=UTC),
    )
    payload_revisado = [dict(payload[0], TEM_MED="11.0")]
    revisao = bronze_clima.gravar_medicoes(
        destino,
        payload_revisado,
        requisicao="/estacao/diaria/2026-10-01/2026-10-01/A001",
        ingerido_em=datetime(2026, 10, 12, 10, 0, tzinfo=UTC),
    )

    assert primeira.linhas_lidas == 1
    assert primeira.linhas_novas == 1
    assert repetida.linhas_novas == 0
    assert revisao.linhas_novas == 1
    medicoes = tabela(destino, "medicao")
    assert len(medicoes) == 2
    assert {linha["temp_media"] for linha in medicoes} == {10.0, 11.0}
    assert all(linha["temp_min"] == 0.0 for linha in medicoes)


def test_gravar_medicoes_guarda_sentinela_como_null_delta(tmp_path: Path) -> None:
    gravacao = bronze_clima.gravar_medicoes(
        tmp_path / "clima",
        [
            {
                "CD_ESTACAO": "A001",
                "DT_MEDICAO": "2026-10-01",
                "TEM_MIN": "-9999",
                "TEM_MAX": "0.0",
                "CHUVA": "0.0",
            }
        ],
        requisicao="/estacao/diaria/2026-10-01/2026-10-01/A001",
        ingerido_em=QUANDO,
    )

    assert gravacao.linhas_novas == 1
    medicao = tabela(tmp_path / "clima", "medicao")[0]
    assert medicao["temp_min"] is None
    assert medicao["temp_max"] == 0.0
    assert medicao["precipitacao_total_mm"] == 0.0


def test_processar_medicoes_busca_estacao_e_persiste_delta(tmp_path: Path) -> None:
    class ClienteFake:
        def buscar_dados_estacao(self, estacao_id, data_inicio, data_fim):
            assert (estacao_id, data_inicio, data_fim) == ("A001", "2026-10-01", "2026-10-02")
            return [
                {
                    "CD_ESTACAO": "A001",
                    "DT_MEDICAO": "2026-10-01",
                    "TEM_MIN": "0.0",
                    "TEM_MAX": "20.0",
                    "CHUVA": "0.0",
                }
            ]

    respostas, medicoes = ingest_clima.processar_medicoes(
        ClienteFake(), ["A001"], "2026-10-01", "2026-10-02", tmp_path / "clima"
    )

    assert respostas == 1
    assert medicoes == 1
    assert tabela(tmp_path / "clima", "medicao")[0]["temp_min"] == 0.0


def test_loader_medicoes_delta_idempotente(tmp_path: Path) -> None:
    destino = tmp_path / "clima"
    bronze_clima.gravar_medicoes(
        destino,
        [
            {
                "CD_ESTACAO": "A001",
                "DT_MEDICAO": "2026-10-01",
                "TEM_MIN": "0.0",
                "TEM_MAX": "20.0",
                "CHUVA": "0.0",
            }
        ],
        requisicao="/estacao/diaria/2026-10-01/2026-10-01/A001",
        ingerido_em=QUANDO,
    )

    import duckdb

    with duckdb.connect(":memory:") as conexao:
        assert carregar_bronze_medicoes(conexao, destino) == 1
        assert carregar_bronze_medicoes(conexao, destino) == 1
        leitura = conexao.execute(
            "select temp_min, precipitacao_total_mm from bronze.clima_medicao"
        ).fetchone()

    assert leitura == (0.0, 0.0)


def test_importar_raw(tmp_path: Path, payload_estacoes) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    caminho_gz = raw_dir / "estacoes.json.gz"
    with gzip.open(caminho_gz, "wt", encoding="utf-8") as f:
        json.dump(payload_estacoes, f)

    destino = tmp_path / "clima"
    respostas, novas, falhas = bronze_clima.importar_raw(raw_dir, destino)

    assert falhas == []
    assert respostas == 1
    assert novas == 671

    # Reimportação idempotente
    respostas2, novas2, falhas2 = bronze_clima.importar_raw(raw_dir, destino)
    assert falhas2 == []
    assert respostas2 == 0
    assert novas2 == 0


def test_checar_tabela(tmp_path: Path, payload_estacoes) -> None:
    destino = tmp_path / "clima"
    bronze_clima.gravar(destino, payload_estacoes)
    info = bronze_clima.checar_tabela(destino)
    assert info["linhas"] == 671
    assert info["estados"] == 27
    assert "Automatica" in info["tipos"]


def test_carregar_duckdb_modos(tmp_path: Path, payload_estacoes) -> None:
    destino = tmp_path / "clima"
    bronze_clima.gravar(destino, payload_estacoes)

    db_path = tmp_path / "teste.duckdb"

    # Modo 1: substitui
    total1 = bronze_clima.carregar_duckdb(destino, db_path, modo="substitui")
    assert total1 == 671

    # Reexecução no modo substitui mantém as 671 estações
    total1_reexec = bronze_clima.carregar_duckdb(destino, db_path, modo="substitui")
    assert total1_reexec == 671

    # Modo 2: so_acrescenta (sem novas estações, total permanece 671)
    total2 = bronze_clima.carregar_duckdb(destino, db_path, modo="so_acrescenta")
    assert total2 == 671
