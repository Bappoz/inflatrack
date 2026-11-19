"""Copia os gráficos do notebook da avaliação para `docs/assets/e4/`, para o mkdocs mostrá-los.

Roda no fim de `just modelo-notebook`, então as imagens da documentação saem da mesma execução do
notebook. `tests/unit/test_predicao_exportar_graficos.py` falha se as duas divergirem.

Uso::

    uv run python -m inflatrack.predicao.exportar_graficos
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
NOTEBOOK = RAIZ / "notebooks" / "avaliacao_modelos.ipynb"
DESTINO = RAIZ / "docs" / "assets" / "e4"

# Na ordem em que os gráficos aparecem no notebook.
NOMES = ("mae_por_modelo", "previsto_contra_real")


def exportar(
    notebook: Path = NOTEBOOK, destino: Path = DESTINO, nomes: tuple[str, ...] | list[str] = NOMES
) -> list[Path]:
    celulas = json.loads(notebook.read_text(encoding="utf-8"))["cells"]
    imagens = [
        saida["data"]["image/png"]
        for celula in celulas
        if celula["cell_type"] == "code"
        for saida in celula.get("outputs", [])
        if "image/png" in saida.get("data", {})
    ]
    if len(imagens) != len(nomes):
        raise ValueError(
            f"o notebook tem {len(imagens)} gráficos e há {len(nomes)} nomes; atualize NOMES"
        )
    destino.mkdir(parents=True, exist_ok=True)
    arquivos = []
    for nome, imagem in zip(nomes, imagens, strict=True):
        arquivo = destino / f"{nome}.png"
        arquivo.write_bytes(base64.b64decode(imagem))
        arquivos.append(arquivo)
    return arquivos


def main() -> int:
    for arquivo in exportar():
        print(arquivo.relative_to(RAIZ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
