"""O notebook da avaliação só apresenta: a lógica fica em `inflatrack.predicao`, que tem testes."""

import json
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[2] / "notebooks" / "avaliacao_modelos.ipynb"


def _celulas_de_codigo() -> list[dict]:
    celulas = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    return [c for c in celulas if c["cell_type"] == "code"]


def _fonte(celula: dict) -> str:
    return "".join(celula["source"])


def test_notebook_usa_o_pacote_e_nao_define_modelo() -> None:
    fontes = [_fonte(c) for c in _celulas_de_codigo()]

    assert any("from inflatrack.predicao" in f for f in fontes)
    assert not any(linha.lstrip().startswith("def ") for f in fontes for linha in f.splitlines())


def test_notebook_nao_le_preco() -> None:
    assert not any("atacado.preco" in _fonte(c) for c in _celulas_de_codigo())


def test_notebook_esta_executado_e_sem_erro() -> None:
    celulas = _celulas_de_codigo()
    saidas = [saida for c in celulas for saida in c.get("outputs", [])]

    assert all(c.get("execution_count") for c in celulas)
    assert not [s for s in saidas if s["output_type"] == "error"]
    assert any(s.get("data", {}).get("image/png") for s in saidas)
