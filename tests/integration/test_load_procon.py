from pathlib import Path

import duckdb
import pytest

from inflatrack.bronze import bronze_procon
from inflatrack.loaders import load_procon

FIXTURE_CSV = Path("tests/fixtures/procon/cesta_basica.csv")


def test_load_procon_duckdb_modos(tmp_path: Path) -> None:
    conteudo = FIXTURE_CSV.read_text(encoding="utf-8")
    delta_dir = tmp_path / "procon_delta"

    bronze_procon.promover_cesta_basica(
        conteudo,
        requisicao=str(FIXTURE_CSV),
        destino=delta_dir,
    )

    with duckdb.connect(":memory:") as conexao:
        # Modo 1: substitui
        total1 = load_procon.carregar_bronze(conexao, delta_dir=delta_dir, modo="substitui")
        assert total1 == 20

        # Reexecução no modo substitui mantém as 20 linhas
        total1_reexec = load_procon.carregar_bronze(conexao, delta_dir=delta_dir, modo="substitui")
        assert total1_reexec == 20

        # Modo 2: so_acrescenta
        total2 = load_procon.carregar_bronze(conexao, delta_dir=delta_dir, modo="so_acrescenta")
        assert total2 == 20

        # Verifica dados gravados
        registro = conexao.execute(
            """
            SELECT produto, preco_medio, codigo_subitem_ipca
            FROM bronze.procon_cesta_basica
            WHERE produto = 'Arroz Agulhinha' AND data_pesquisa = '2026-07-01'
            """
        ).fetchone()
        assert registro == ("Arroz Agulhinha", 28.90, "1101002")


def test_load_procon_modo_invalido(tmp_path: Path) -> None:
    with (
        duckdb.connect(":memory:") as conexao,
        pytest.raises(ValueError, match="Modo de carga inválido"),
    ):
        load_procon.carregar_bronze(conexao, delta_dir=tmp_path, modo="modo_errado")
