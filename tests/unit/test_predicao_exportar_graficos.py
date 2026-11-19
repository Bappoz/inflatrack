from pathlib import Path

import pytest

from inflatrack.predicao.exportar_graficos import NOMES, exportar

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "avaliacao_modelos.ipynb"
PNG = b"\x89PNG\r\n\x1a\n"


def test_exporta_um_png_por_grafico_do_notebook(tmp_path: Path) -> None:
    arquivos = exportar(NOTEBOOK, tmp_path)

    assert [a.name for a in arquivos] == [f"{nome}.png" for nome in NOMES]
    assert all(a.read_bytes().startswith(PNG) for a in arquivos)


def test_numero_de_graficos_diferente_dos_nomes_falha(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="gráficos"):
        exportar(NOTEBOOK, tmp_path, nomes=["so_um"])


def test_imagens_da_documentacao_batem_com_o_notebook(tmp_path: Path) -> None:
    """Se o notebook foi refeito e as imagens do mkdocs não, a página mostra gráfico velho."""
    documentacao = NOTEBOOK.parents[1] / "docs" / "assets" / "e4"

    for novo in exportar(NOTEBOOK, tmp_path):
        assert (documentacao / novo.name).read_bytes() == novo.read_bytes()
