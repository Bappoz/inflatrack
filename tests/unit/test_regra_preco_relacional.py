"""Preço de produto fica só no Postgres (ADR 0004): guarda da regra e da tabela de exemplo."""

from pathlib import Path

from inflatrack.atacado.importar_tabela import ler_csv

RAIZ = Path(__file__).resolve().parents[2]
TABELA_EXEMPLO = RAIZ / "data" / "atacado" / "tabela_exemplo.csv"
PIPELINE_ANALITICO = ("dbt", "src/inflatrack/bronze", "src/inflatrack/loaders", "orchestration")


def test_tabela_exemplo_e_valida() -> None:
    linhas = ler_csv(TABELA_EXEMPLO.read_text(encoding="utf-8"))

    assert len(linhas) >= 35
    assert all(len(linha.codigo_subitem_ipca) == 7 for linha in linhas)
    grupos = {linha.codigo_subitem_ipca[:2] for linha in linhas}
    assert {"11", "21", "63"} <= grupos  # alimentação, limpeza e higiene


def test_preco_nao_entra_no_pipeline_analitico() -> None:
    citacoes = [
        str(arquivo.relative_to(RAIZ))
        for pasta in PIPELINE_ANALITICO
        for arquivo in (RAIZ / pasta).rglob("*")
        if arquivo.suffix in {".py", ".sql", ".yml", ".yaml"}
        and "atacado" in arquivo.read_text(encoding="utf-8", errors="ignore").lower()
    ]

    assert citacoes == []
