from datetime import date
from pathlib import Path

import pytest
from deltalake import DeltaTable

from inflatrack.bronze import bronze_procon
from inflatrack.clients.procon import ProconError, extrair_cesta_basica

CSV_MOCK = (
    "data_pesquisa;produto;unidade;preco_medio;preco_minimo;preco_maximo;praca;codigo_subitem_ipca\n"
    "2026-08-01;Arroz Agulhinha;5 kg;29,40;25,00;33,50;Brasília;1101002\n"
    "2026-08-01;Feijão Carioca;1 kg;8,10;6,80;9,50;Brasília;1101012\n"
    "2026-08-01;Óleo de Soja;900 ml;7,10;6,20;8,15;Brasília;1101032\n"
)


def test_extrair_cesta_basica_sucesso() -> None:
    linhas = extrair_cesta_basica(CSV_MOCK)
    assert len(linhas) == 3

    arroz = linhas[0]
    assert arroz["data_pesquisa"] == date(2026, 8, 1)
    assert arroz["produto"] == "Arroz Agulhinha"
    assert arroz["unidade"] == "5 kg"
    assert arroz["preco_medio"] == 29.40
    assert arroz["preco_minimo"] == 25.00
    assert arroz["preco_maximo"] == 33.50
    assert arroz["praca"] == "Brasília"
    assert arroz["codigo_subitem_ipca"] == "1101002"


def test_extrair_cesta_basica_rejeita_csv_vazio() -> None:
    with pytest.raises(ProconError, match="vazio"):
        extrair_cesta_basica("   ")


def test_extrair_cesta_basica_rejeita_colunas_faltantes() -> None:
    csv_incompleto = "produto;preco_medio\nArroz;25.00"
    with pytest.raises(ProconError, match="Colunas obrigatórias ausentes"):
        extrair_cesta_basica(csv_incompleto)


def test_extrair_cesta_basica_rejeita_preco_invalido() -> None:
    csv_invalido = (
        "data_pesquisa;produto;unidade;preco_medio;praca\n2026-08-01;Arroz;5 kg;abc;Brasília"
    )
    with pytest.raises(ProconError, match="Valor numérico inválido"):
        extrair_cesta_basica(csv_invalido)


def test_promover_cesta_basica_delta_e_idempotencia(tmp_path: Path) -> None:
    destino = tmp_path / "procon_delta"

    # Primeira execução: insere registros
    gravacao1 = bronze_procon.promover_cesta_basica(
        CSV_MOCK,
        requisicao="teste_mock",
        destino=destino,
    )
    assert gravacao1.respostas_novas == 1
    assert gravacao1.linhas_lidas == 3
    assert gravacao1.linhas_novas == 3

    caminho_tabela = destino / "cesta_basica"
    assert DeltaTable.is_deltatable(str(caminho_tabela))
    dt = DeltaTable(str(caminho_tabela))
    assert dt.to_pyarrow_table().num_rows == 3

    # Segunda execução idêntica: idempotente, 0 linhas novas
    gravacao2 = bronze_procon.promover_cesta_basica(
        CSV_MOCK,
        requisicao="teste_mock",
        destino=destino,
    )
    assert gravacao2.respostas_novas == 0
    assert gravacao2.linhas_novas == 0
    assert dt.to_pyarrow_table().num_rows == 3
