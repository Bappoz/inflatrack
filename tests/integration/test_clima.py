"""Testes da camada Bronze em Delta para Dados do Clima (INMET).

Cobre o catálogo (transformação fiel sem valores padrão inventados, checagens de integridade
geográfica e volume, importação do Raw) e as medições do BDMEP (CSV no Raw, idempotência,
revisão, manifesto do pacote anual e falha parcial), além da carga no DuckDB.
"""

import gzip
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from deltalake import DeltaTable

from inflatrack.bronze import clima as bronze_clima
from inflatrack.loaders.load_clima import carregar_bronze_medicoes
from tests.clima_bdmep import ClienteBdmepFalso, csv_bdmep

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


def _pacotes(*anos: int) -> dict[int, dict[str, str]]:
    """Um pacote por ano com A001 (Brasília) e A002 (Goiânia), dois dias de janeiro cada."""
    return {
        ano: {
            estacao: csv_bdmep(
                estacao, {date(ano, 1, 1): (20.0 + i, 0.5), date(ano, 1, 2): (21.0 + i, 0.0)}
            )
            for i, estacao in enumerate(("A001", "A002"))
        }
        for ano in anos
    }


def test_gravar_csvs_bdmep_idempotente_e_preserva_revisao(tmp_path: Path) -> None:
    destino = tmp_path / "clima"
    texto = csv_bdmep("A001", {date(2026, 10, 1): (10.0, 0.0)})
    requisicao = "https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip#A001.CSV"

    primeira = bronze_clima.gravar_csvs_bdmep(destino, [(requisicao, texto)], QUANDO)
    repetida = bronze_clima.gravar_csvs_bdmep(destino, [(requisicao, texto)], QUANDO)
    revisado = csv_bdmep("A001", {date(2026, 10, 1): (11.0, 0.0)})
    revisao = bronze_clima.gravar_csvs_bdmep(destino, [(requisicao, revisado)], QUANDO)

    assert (primeira.respostas_novas, primeira.linhas_lidas, primeira.linhas_novas) == (1, 1, 1)
    assert (repetida.respostas_novas, repetida.linhas_novas) == (0, 0)
    assert (revisao.respostas_novas, revisao.linhas_novas) == (1, 1)
    medicoes = tabela(destino, "medicao")
    assert {linha["temp_media"] for linha in medicoes} == {10.0, 11.0}
    assert all(linha["precipitacao_total_mm"] == 0.0 for linha in medicoes)
    respostas = tabela(destino, "resposta")
    assert {r["tipo_conteudo"] for r in respostas} == {bronze_clima.TIPO_CSV_BDMEP}
    assert {r["corpo"] for r in respostas} == {texto, revisado}


def test_csv_sem_dia_valido_nao_entra_no_raw(tmp_path: Path) -> None:
    destino = tmp_path / "clima"
    vazio = csv_bdmep("A001", {}) + "2026/10/01;0000 UTC" + ";" * 18 + "\n"

    gravacao = bronze_clima.gravar_csvs_bdmep(destino, [("x#A001.CSV", vazio)], QUANDO)

    assert gravacao == bronze_clima.GravacaoMedicoes(0, 0, 0)
    assert not DeltaTable.is_deltatable(str(destino / "resposta"))


def test_processar_medicoes_grava_estacoes_pedidas_e_pula_pacote_sem_mudanca(
    tmp_path: Path,
) -> None:
    destino = tmp_path / "clima"
    cliente = ClienteBdmepFalso(_pacotes(2024, 2025))

    primeira = bronze_clima.processar_medicoes(
        cliente, ["A001"], [2024, 2025, 2026], destino, ano_corrente=2026
    )

    assert primeira.anos_processados == [2024, 2025]
    assert primeira.anos_nao_publicados == [2026]
    assert (primeira.respostas_novas, primeira.medicoes_novas, primeira.falhas) == (2, 4, [])
    assert {linha["estacao_id"] for linha in tabela(destino, "medicao")} == {"A001"}
    manifestos = [
        r for r in tabela(destino, "resposta") if r["tipo_conteudo"] == bronze_clima.TIPO_MANIFESTO
    ]
    assert len(manifestos) == 2

    segunda = bronze_clima.processar_medicoes(cliente, ["A001"], [2024, 2025], destino)

    assert segunda.anos_inalterados == [2024, 2025]
    assert cliente.baixados == [2024, 2025]  # nada foi baixado de novo


def test_processar_medicoes_baixa_de_novo_quando_o_inmet_republica_ou_o_de_para_muda(
    tmp_path: Path,
) -> None:
    destino = tmp_path / "clima"
    cliente = ClienteBdmepFalso(_pacotes(2025))
    bronze_clima.processar_medicoes(cliente, ["A001"], [2025], destino)

    # Estação nova no de-para: o mesmo pacote é relido só para trazê-la.
    novo_de_para = bronze_clima.processar_medicoes(cliente, ["A001", "A002"], [2025], destino)
    # O INMET republica o pacote: baixa, mas leituras idênticas não duplicam.
    cliente.versao = "v2"
    republicado = bronze_clima.processar_medicoes(cliente, ["A001", "A002"], [2025], destino)

    assert cliente.baixados == [2025, 2025, 2025]
    assert (novo_de_para.respostas_novas, novo_de_para.medicoes_novas) == (1, 2)
    assert (republicado.respostas_novas, republicado.medicoes_novas) == (0, 0)
    assert len(tabela(destino, "medicao")) == 4


def test_falha_num_ano_nao_impede_os_outros_e_e_retentada(tmp_path: Path) -> None:
    destino = tmp_path / "clima"
    cliente = ClienteBdmepFalso(_pacotes(2024, 2025))
    cliente.falhar_em = {2024}

    com_falha = bronze_clima.processar_medicoes(cliente, ["A001"], [2024, 2025], destino)
    cliente.falhar_em = set()
    retentativa = bronze_clima.processar_medicoes(cliente, ["A001"], [2024, 2025], destino)

    assert com_falha.anos_processados == [2025]
    assert com_falha.falhas and com_falha.falhas[0].startswith("2024:")
    assert retentativa.anos_processados == [2024]
    assert retentativa.anos_inalterados == [2025]


def _manifestos(destino: Path) -> list[dict]:
    if not DeltaTable.is_deltatable(str(destino / "resposta")):
        return []
    return [
        r for r in tabela(destino, "resposta") if r["tipo_conteudo"] == bronze_clima.TIPO_MANIFESTO
    ]


def test_ano_encerrado_sem_pacote_e_falha_nao_ano_nao_publicado(tmp_path: Path) -> None:
    cliente = ClienteBdmepFalso(_pacotes(2025))

    resumo = bronze_clima.processar_medicoes(
        cliente, ["A001"], [2024, 2025], tmp_path / "clima", ano_corrente=2026
    )

    assert resumo.anos_nao_publicados == []
    assert resumo.falhas and resumo.falhas[0].startswith("2024:")
    assert resumo.anos_processados == [2025]


def test_pacote_sem_nenhuma_estacao_pedida_falha_e_nao_grava_manifesto(tmp_path: Path) -> None:
    destino = tmp_path / "clima"
    cliente = ClienteBdmepFalso(_pacotes(2025))

    resumo = bronze_clima.processar_medicoes(cliente, ["A999"], [2025], destino)

    assert resumo.falhas and "nenhuma das estações" in resumo.falhas[0]
    assert _manifestos(destino) == []


def test_csv_recusado_nao_derruba_as_outras_estacoes_e_o_ano_e_retentado(tmp_path: Path) -> None:
    destino = tmp_path / "clima"
    pacotes = _pacotes(2025)
    pacotes[2025]["A002"] = pacotes[2025]["A002"].replace("PRECIPITAÇÃO TOTAL", "CHUVA")
    cliente = ClienteBdmepFalso(pacotes)

    resumo = bronze_clima.processar_medicoes(cliente, ["A001", "A002"], [2025], destino)

    assert resumo.anos_processados == []
    assert len(resumo.falhas) == 1 and "A002" in resumo.falhas[0]
    assert {linha["estacao_id"] for linha in tabela(destino, "medicao")} == {"A001"}
    assert _manifestos(destino) == []  # a próxima coleta baixa de novo


def test_codigo_do_cabecalho_diferente_do_nome_do_arquivo_e_recusado(tmp_path: Path) -> None:
    texto = csv_bdmep("A002", {date(2025, 1, 1): (20.0, 0.0)})
    requisicao = "https://x/2025.zip#2025/INMET_CO_DF_A001_BRASILIA_01-01-2025_A_31-12-2025.CSV"

    gravacao = bronze_clima.gravar_csvs_bdmep(tmp_path / "clima", [(requisicao, texto)], QUANDO)

    assert gravacao.linhas_lidas == 0
    assert gravacao.falhas and "A002" in gravacao.falhas[0]


def test_mesma_leitura_em_dois_arquivos_do_lote_entra_uma_vez(tmp_path: Path) -> None:
    import duckdb

    destino = tmp_path / "clima"
    texto = csv_bdmep("A001", {date(2025, 1, 1): (20.0, 0.0)})
    arquivos = [("x#parte1.CSV", texto), ("x#parte2.CSV", texto + "\n")]

    gravacao = bronze_clima.gravar_csvs_bdmep(destino, arquivos, QUANDO)

    assert gravacao.linhas_novas == 1
    with duckdb.connect(":memory:") as conexao:
        assert carregar_bronze_medicoes(conexao, destino) == 1


def test_mudar_a_versao_da_leitura_rele_o_pacote(tmp_path: Path, monkeypatch) -> None:
    destino = tmp_path / "clima"
    cliente = ClienteBdmepFalso(_pacotes(2025))
    bronze_clima.processar_medicoes(cliente, ["A001"], [2025], destino)

    monkeypatch.setattr(bronze_clima, "VERSAO_LEITURA", bronze_clima.VERSAO_LEITURA + 1)
    bronze_clima.processar_medicoes(cliente, ["A001"], [2025], destino)

    assert cliente.baixados == [2025, 2025]


def test_loader_medicoes_delta_idempotente(tmp_path: Path) -> None:
    destino = tmp_path / "clima"
    texto = csv_bdmep("A001", {date(2026, 10, 1): (0.0, 0.0)})
    bronze_clima.gravar_csvs_bdmep(destino, [("x#A001.CSV", texto)], QUANDO)

    import duckdb

    with duckdb.connect(":memory:") as conexao:
        assert carregar_bronze_medicoes(conexao, destino) == 1
        assert carregar_bronze_medicoes(conexao, destino) == 1
        leitura = conexao.execute(
            "select temp_min, precipitacao_total_mm, horas_com_registro from bronze.clima_medicao"
        ).fetchone()

    assert leitura == (-0.5, 0.0, 24)


def test_ddl_acrescenta_horas_em_banco_criado_antes_do_bdmep(tmp_path: Path) -> None:
    import duckdb

    from inflatrack.loaders.load_clima import SCHEMA_SQL

    db = tmp_path / "antigo.duckdb"
    with duckdb.connect(str(db)) as conexao:
        conexao.execute("create schema bronze")
        conexao.execute(
            "create table bronze.clima_medicao (id_medicao varchar primary key, "
            "estacao_id varchar not null, data_referencia date not null, temp_min double, "
            "temp_max double, temp_media double, precipitacao_total_mm double, "
            "umidade_relativa_media_pct double, umidade_relativa_min_pct double, "
            "observado boolean not null, _id_resposta varchar not null, _fonte varchar not null, "
            "_requisicao varchar not null, _ingerido_em timestamptz not null)"
        )
        conexao.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        colunas = {c[0] for c in conexao.execute("describe bronze.clima_medicao").fetchall()}

    assert "horas_com_registro" in colunas


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


def test_inicializacao_sem_delta_cria_bronze_e_preserva_dados(
    tmp_path, monkeypatch, payload_estacoes
) -> None:
    import duckdb

    from inflatrack.loaders.load_clima import carregar_bronze_estacoes
    from scripts.init_db import init_db

    db = tmp_path / "banco" / "teste.duckdb"
    monkeypatch.setenv("DBT_DUCKDB_PATH", str(db))
    init_db()
    with duckdb.connect(str(db)) as conexao:
        assert conexao.execute("select count(*) from bronze.clima_estacao").fetchone() == (0,)
        assert conexao.execute("select count(*) from bronze.clima_medicao").fetchone() == (0,)
        destino = tmp_path / "delta"
        bronze_clima.gravar(destino, payload_estacoes, ingerido_em=QUANDO)
        assert carregar_bronze_estacoes(conexao, destino) == 671
    init_db()
    with duckdb.connect(str(db)) as conexao:
        assert conexao.execute("select count(*) from bronze.clima_estacao").fetchone() == (671,)


def test_loader_sem_delta_prepara_tabelas_mas_nao_reporta_carga_com_sucesso(tmp_path):
    import duckdb

    from inflatrack import load_clima

    db = tmp_path / "teste.duckdb"
    assert (
        load_clima.main(
            [
                "--db",
                str(db),
                "--delta-dir",
                str(tmp_path / "ausente"),
                "--parquet-estacoes",
                str(tmp_path / "ausente.parquet"),
                "--parquet-clima",
                str(tmp_path / "ausente_diario.parquet"),
            ]
        )
        == 1
    )
    with duckdb.connect(str(db)) as conexao:
        assert conexao.execute("select count(*) from bronze.clima_estacao").fetchone() == (0,)
        assert conexao.execute("select count(*) from bronze.clima_medicao").fetchone() == (0,)


def test_dbt_clima_build_em_banco_vazio_sem_ingestao(tmp_path, monkeypatch):
    import duckdb

    from scripts.init_db import init_db

    db = tmp_path / "vazio.duckdb"
    monkeypatch.setenv("DBT_DUCKDB_PATH", str(db))
    init_db()
    raiz = Path(__file__).resolve().parents[2]
    resultado = subprocess.run(
        [
            sys.executable,
            "-m",
            "dbt.cli.main",
            "build",
            "--project-dir",
            str(raiz),
            "--profiles-dir",
            str(raiz),
            "--target-path",
            str(tmp_path / "target"),
            "--log-path",
            str(tmp_path / "logs"),
            "--indirect-selection",
            "cautious",
            "--select",
            "+fct_clima_mensal",
            "stg_clima__estacao",
        ],
        cwd=raiz,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    with duckdb.connect(str(db)) as conexao:
        assert conexao.execute(
            "select count(*) from silver.int_clima__anomalia_mensal"
        ).fetchone() == (0,)
        assert conexao.execute("select count(*) from silver.stg_clima__estacao").fetchone() == (0,)
        assert conexao.execute("select count(*) from gold.fct_clima_mensal").fetchone() == (0,)
