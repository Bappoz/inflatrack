"""O notebook da avaliação só apresenta: a lógica fica em `inflatrack.predicao`, que tem testes."""

import json
from pathlib import Path

import pytest

PASTA = Path(__file__).resolve().parents[2] / "notebooks"
NOTEBOOKS = ["avaliacao_modelos.ipynb", "avaliacao_todas_pracas.ipynb"]
pytestmark = pytest.mark.parametrize("nome", NOTEBOOKS)


def _celulas_de_codigo(nome: str) -> list[dict]:
    celulas = json.loads((PASTA / nome).read_text(encoding="utf-8"))["cells"]
    return [c for c in celulas if c["cell_type"] == "code"]


def _fonte(celula: dict) -> str:
    return "".join(celula["source"])


def test_notebook_usa_o_pacote_e_nao_define_modelo(nome: str) -> None:
    fontes = [_fonte(c) for c in _celulas_de_codigo(nome)]

    assert any("from inflatrack.predicao" in f for f in fontes)
    assert not any(linha.lstrip().startswith("def ") for f in fontes for linha in f.splitlines())


def test_notebook_nao_le_preco(nome: str) -> None:
    assert not any("atacado.preco" in _fonte(c) for c in _celulas_de_codigo(nome))


def test_notebook_esta_executado_e_sem_erro(nome: str) -> None:
    celulas = _celulas_de_codigo(nome)
    saidas = [saida for c in celulas for saida in c.get("outputs", [])]

    assert all(c.get("execution_count") for c in celulas)
    assert not [s for s in saidas if s["output_type"] == "error"]
    assert any(s.get("data", {}).get("image/png") for s in saidas)
