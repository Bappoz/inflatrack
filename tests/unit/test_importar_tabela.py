from datetime import date

import pytest

from inflatrack.atacado.importar_tabela import LinhaPreco, ler_csv

CABECALHO = "produto;unidade;preco;codigo_subitem_ipca;vigente_desde"


def test_le_linhas_em_formato_brasileiro() -> None:
    conteudo = f"{CABECALHO}\nArroz Tipo 1;5 kg;R$ 24,90;1101002;01/11/2026\n"

    assert ler_csv(conteudo) == [
        LinhaPreco("Arroz Tipo 1", "5 kg", 2490, "1101002", date(2026, 11, 1))
    ]


def test_tira_o_bom_do_excel() -> None:
    conteudo = f"﻿{CABECALHO}\nArroz;5 kg;24,90;1101002;2026-11-01\n"

    assert ler_csv(conteudo)[0].produto == "Arroz"


def test_aceita_virgula_como_separador() -> None:
    conteudo = (
        "produto,unidade,preco,codigo_subitem_ipca,vigente_desde\n"
        "Arroz,5 kg,24.90,1101002,2026-11-01\n"
    )

    assert ler_csv(conteudo)[0].preco_centavos == 2490


def test_coluna_faltando_e_citada() -> None:
    conteudo = "produto;unidade;preco;vigente_desde\nArroz;5 kg;24,90;2026-11-01\n"

    with pytest.raises(ValueError, match="codigo_subitem_ipca"):
        ler_csv(conteudo)


def test_preco_invalido_cita_a_linha() -> None:
    conteudo = (
        f"{CABECALHO}\nArroz;5 kg;24,90;1101002;2026-11-01\nFeijão;1 kg;7,955;1101073;2026-11-01\n"
    )

    with pytest.raises(ValueError, match="linha 3"):
        ler_csv(conteudo)


def test_mesmo_produto_e_data_com_precos_diferentes_e_recusado() -> None:
    conteudo = (
        f"{CABECALHO}\nArroz;5 kg;24,90;1101002;2026-11-01\nArroz;5 kg;25,90;1101002;2026-11-01\n"
    )

    with pytest.raises(ValueError, match="Arroz"):
        ler_csv(conteudo)


def test_arquivo_sem_linhas_e_recusado() -> None:
    with pytest.raises(ValueError):
        ler_csv(f"{CABECALHO}\n")
