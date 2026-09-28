from pathlib import Path

import duckdb
import pytest

from inflatrack.dieese import DieeseError, extrair_tabela
from inflatrack.load_salario_minimo import carregar

HTML_MOCK = """
<html>
<body>
<table rules="all">
<thead>
<tr><th>Período</th><th>Salário mínimo nominal</th><th>Salário mínimo necessário</th></tr>
</thead>
<tbody>
<tr class="subtitulo"><td colspan="3">2026</td></tr>
<tr><td>Agosto</td><td>R$ 1.621,00</td><td>R$ 7.565,86</td></tr>
<tr><td>Julho</td><td>R$ 1.621,00</td><td>R$ 7.687,01</td></tr>
<tr class="subtitulo"><td colspan="3">2025</td></tr>
<tr><td>Dezembro</td><td>R$ 1.518,00</td><td>R$ 7.200,00</td></tr>
</tbody>
</table>
</body>
</html>
"""


def test_extrair_tabela_normaliza_corretamente() -> None:
    df = extrair_tabela(HTML_MOCK)

    assert len(df) == 3
    assert df["ano_mes"].tolist() == ["2025-12", "2026-07", "2026-08"]

    linha_ago = df.loc[df["ano_mes"] == "2026-08"].iloc[0]
    assert linha_ago["salario_nominal"] == 1621.0
    assert linha_ago["salario_necessario"] == 7565.86
    assert linha_ago["ano"] == 2026
    assert linha_ago["mes"] == 8
    assert linha_ago["multiplo_necessario_nominal"] == round(7565.86 / 1621.0, 4)


def test_extrair_tabela_rejeita_html_sem_tabela() -> None:
    with pytest.raises(DieeseError):
        extrair_tabela("<html><body><p>Sem tabela aqui</p></body></html>")


def test_extrair_tabela_rejeita_tabela_vazia() -> None:
    with pytest.raises(DieeseError):
        extrair_tabela("<table><tr><th>Período</th></tr></table>")


def test_carregar_salario_minimo_upsert_idempotente(tmp_path: Path) -> None:
    parquet = tmp_path / "salario_minimo.parquet"
    extrair_tabela(HTML_MOCK).to_parquet(parquet)

    with duckdb.connect(":memory:") as conexao:
        assert carregar(conexao, parquet) == 3
        # Idempotência: rodar novamente não duplica linhas
        assert carregar(conexao, parquet) == 3

        resultado = conexao.execute(
            "SELECT salario_nominal, salario_necessario "
            "FROM salario_minimo WHERE ano_mes = '2026-08'"
        ).fetchone()
        assert resultado == (1621.0, 7565.86)
