"""Leitura do CSV horário do BDMEP (INMET) e validação da CLI de coleta, sem rede."""

from datetime import date
from unittest.mock import patch

import pytest

from inflatrack.bronze import clima
from tests.clima_bdmep import CSV_2006, CSV_2019, CSV_2025, csv_bdmep


def _ler(caminho) -> str:
    return caminho.read_text(encoding="latin-1")


def test_csv_de_2025_vira_um_dia_por_data_utc() -> None:
    leitura = clima.transformar_csv_bdmep(_ler(CSV_2025))

    assert leitura.estacao_id == "A001"
    assert [linha["data_referencia"] for linha in leitura.linhas] == [
        date(2025, 1, 1),
        date(2025, 1, 2),
    ]
    primeiro = leitura.linhas[0]
    assert primeiro["horas_com_registro"] == 24
    assert primeiro["observado"] is True
    assert primeiro["temp_min"] <= primeiro["temp_media"] <= primeiro["temp_max"]
    assert 0 <= primeiro["umidade_relativa_min_pct"] <= primeiro["umidade_relativa_media_pct"]


def test_csv_de_2006_tem_outro_cabecalho_e_o_mesmo_resultado() -> None:
    """Até 2018 o cabeçalho é 'DATA (YYYY-MM-DD);HORA (UTC)' e a ausência é -9999."""
    leitura = clima.transformar_csv_bdmep(_ler(CSV_2006))

    assert leitura.estacao_id == "A001"
    assert [linha["data_referencia"] for linha in leitura.linhas] == [date(2006, 1, 1)]
    dia = leitura.linhas[0]
    assert dia["horas_com_registro"] == 24
    assert dia["temp_media"] is not None
    assert dia["precipitacao_total_mm"] is not None


def test_csv_de_2019_com_acentos_trocados_por_interrogacao() -> None:
    """Visto na carga real: 'DATA DE FUNDAC?O' não pode ser lido como cabeçalho dos dados."""
    leitura = clima.transformar_csv_bdmep(_ler(CSV_2019))

    assert leitura.estacao_id == "A001"
    assert [linha["data_referencia"] for linha in leitura.linhas] == [date(2019, 1, 1)]
    assert leitura.linhas[0]["precipitacao_total_mm"] is not None


def test_agregacao_do_dia_confere_com_a_conta_feita_fora() -> None:
    texto = csv_bdmep("A001", {date(2024, 1, 1): (20.0, 0.5)})

    (dia,) = clima.transformar_csv_bdmep(texto).linhas

    assert dia["temp_media"] == 20.0
    assert dia["temp_max"] == 20.5
    assert dia["temp_min"] == 19.5
    assert dia["precipitacao_total_mm"] == 12.0  # 24 h x 0,5 mm
    assert dia["umidade_relativa_media_pct"] == 70.0
    assert dia["umidade_relativa_min_pct"] == 65.0


def test_zero_e_medida_e_menos_9999_e_ausencia() -> None:
    texto = csv_bdmep("A001", {date(2024, 1, 1): (0.0, 0.0)}).replace(
        "2024/01/01;0000 UTC;0,0", "2024/01/01;0000 UTC;-9999"
    )

    (dia,) = clima.transformar_csv_bdmep(texto).linhas

    assert dia["temp_media"] == 0.0
    assert dia["precipitacao_total_mm"] == 0.0  # 23 horas medidas, todas com zero
    assert dia["horas_com_registro"] == 24


def test_hora_repetida_no_csv_conta_uma_vez_e_vale_a_ultima() -> None:
    texto = csv_bdmep("A001", {date(2024, 1, 1): (20.0, 0.5)})
    repetida = next(linha for linha in texto.splitlines() if linha.startswith("2024/01/01;0000"))
    corrigida = repetida.replace(";0,5;", ";1,5;", 1)

    (dia,) = clima.transformar_csv_bdmep(texto + corrigida + "\n").linhas

    assert dia["horas_com_registro"] == 24
    assert dia["precipitacao_total_mm"] == 13.0  # 23 x 0,5 + 1,5 da linha que vale


def test_dia_com_poucas_horas_fica_sem_metrica_mas_registra_as_horas() -> None:
    poucas = clima.HORAS_MINIMAS - 1
    texto = csv_bdmep("A001", {date(2024, 1, 1): (25.0, 1.0)}, horas=poucas)

    (dia,) = clima.transformar_csv_bdmep(texto).linhas

    assert dia["horas_com_registro"] == poucas
    assert dia["temp_media"] is None
    assert dia["precipitacao_total_mm"] is None


def test_hora_toda_vazia_nao_conta_e_dia_vazio_nao_vira_linha() -> None:
    texto = csv_bdmep("A001", {date(2024, 1, 1): (25.0, 1.0)})
    vazio = "2024/01/02;0000 UTC" + ";" * 18
    leitura = clima.transformar_csv_bdmep(texto + vazio + "\n")

    assert [linha["data_referencia"] for linha in leitura.linhas] == [date(2024, 1, 1)]


def test_leitura_fora_da_faixa_fisica_vira_nulo() -> None:
    texto = csv_bdmep("A001", {date(2024, 1, 1): (99.0, 0.0)})

    (dia,) = clima.transformar_csv_bdmep(texto).linhas

    assert dia["temp_media"] is None
    assert dia["precipitacao_total_mm"] == 0.0


def test_csv_sem_coluna_esperada_falha_explicitamente() -> None:
    texto = _ler(CSV_2025).replace("PRECIPITAÇÃO TOTAL, HORÁRIO (mm)", "CHUVA")

    with pytest.raises(clima.ChecagemError, match="PRECIPITACAO TOTAL"):
        clima.transformar_csv_bdmep(texto)


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("2025/INMET_CO_DF_A001_BRASILIA_01-01-2025_A_31-12-2025.CSV", "A001"),
        ("2025/INMET_S_RS_B827_BAGE - CENTRO_01-08-2025_A_20-10-2025.CSV", "B827"),
        ("2006/INMET_SE_RJ_A652_RIO DE JANEIRO_01-01-2006_A_31-12-2006.CSV", "A652"),
        ("2025/", None),
        ("LEIAME.txt", None),
    ],
)
def test_estacao_do_arquivo(nome, esperado) -> None:
    assert clima.estacao_do_arquivo(nome) == esperado


def test_de_para_tem_uma_estacao_por_praca_do_ipca() -> None:
    estacoes = clima.estacoes_mapeadas()

    assert len(estacoes) == len(set(estacoes)) == 16
    assert "A305" in estacoes  # Fortaleza


def test_de_para_vazio_falha_explicitamente(tmp_path) -> None:
    caminho = tmp_path / "estacoes.csv"
    caminho.write_text("estacao_id,codigo_localidade,justificativa\n", encoding="utf-8")

    with pytest.raises(clima.ChecagemError, match="vazio ou inválido"):
        clima.estacoes_mapeadas(caminho)


def test_anos_padrao_vao_de_2006_ao_ano_corrente() -> None:
    assert clima.anos_padrao(date(2027, 1, 3)) == list(range(2006, 2028))


def test_medicoes_usam_de_para_e_todos_os_anos_por_padrao() -> None:
    with (
        patch.object(clima, "anos_padrao", return_value=[2025, 2026]),
        patch.object(clima, "processar_estacoes") as catalogo,
        patch.object(clima, "processar_medicoes", return_value=clima.ResumoMedicoes()) as coletar,
    ):
        assert clima.main(["coletar", "--medicoes"]) == 0

    catalogo.assert_not_called()
    _, estacoes, anos, _ = coletar.call_args.args
    assert estacoes == clima.estacoes_mapeadas()
    assert anos == [2025, 2026]


def test_medicoes_respeitam_estacoes_e_anos_explicitos() -> None:
    with patch.object(clima, "processar_medicoes", return_value=clima.ResumoMedicoes()) as coletar:
        argumentos = ["coletar", "--medicoes", "--estacao", "A001", "--de-ano", "2010"]
        assert clima.main([*argumentos, "--ate-ano", "2012"]) == 0

    assert coletar.call_args.args[1:3] == (["A001"], [2010, 2011, 2012])


def test_falha_em_algum_ano_deixa_a_coleta_vermelha() -> None:
    resumo = clima.ResumoMedicoes(falhas=["2010: queda"])
    with patch.object(clima, "processar_medicoes", return_value=resumo):
        assert clima.main(["coletar", "--medicoes", "--de-ano", "2010", "--ate-ano", "2010"]) == 1


@pytest.mark.parametrize(
    "argumentos",
    [
        ["coletar", "--apenas-estacoes", "--medicoes"],
        ["coletar", "--estacao", "A001"],
        ["coletar", "--de-ano", "2010"],
        ["coletar", "--medicoes", "--de-ano", "2012", "--ate-ano", "2010"],
    ],
)
def test_config_invalida_falha_antes_da_rede(argumentos) -> None:
    with (
        patch.object(clima, "processar_estacoes") as catalogo,
        patch.object(clima, "processar_medicoes") as coletar,
        pytest.raises(SystemExit) as erro,
    ):
        clima.main(argumentos)

    assert erro.value.code == 2
    catalogo.assert_not_called()
    coletar.assert_not_called()


def test_sem_medicoes_coleta_so_o_catalogo() -> None:
    with (
        patch.object(clima, "processar_estacoes") as catalogo,
        patch.object(clima, "processar_medicoes") as coletar,
    ):
        assert clima.main(["coletar", "--apenas-estacoes"]) == 0

    catalogo.assert_called_once()
    coletar.assert_not_called()
