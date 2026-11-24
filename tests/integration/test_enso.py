"""RONI em Delta, carga no DuckDB e o fato gold.fct_enso_mensal pelo dbt real."""

import os
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from deltalake import DeltaTable

from inflatrack.bronze import enso
from inflatrack.loaders import load_enso

RAIZ = Path(__file__).resolve().parents[2]
TEXTO = (RAIZ / "tests" / "fixtures" / "enso" / "RONI.ascii.txt").read_text(encoding="utf-8")
QUANDO = datetime(2026, 11, 11, 12, tzinfo=UTC)


def _tabela(destino: Path, nome: str) -> list[dict]:
    return DeltaTable(str(destino / nome)).to_pyarrow_table().to_pylist()


def test_gravar_e_idempotente_e_guarda_a_revisao(tmp_path: Path) -> None:
    destino = tmp_path / "enso"

    primeira = enso.gravar(destino, TEXTO, "https://noaa/RONI.ascii.txt", QUANDO)
    repetida = enso.gravar(destino, TEXTO, "https://noaa/RONI.ascii.txt", QUANDO)
    revisado = TEXTO.replace("JJA  2026  1.36", "JJA  2026  1.40")
    revisao = enso.gravar(destino, revisado, "https://noaa/RONI.ascii.txt", QUANDO)

    assert (primeira.resposta_nova, primeira.linhas_novas) == (True, 921)
    assert (repetida.resposta_nova, repetida.linhas_novas) == (False, 0)
    assert (revisao.resposta_nova, revisao.linhas_novas) == (True, 1)
    assert len(_tabela(destino, "resposta")) == 2
    jja = [x for x in _tabela(destino, "roni") if x["mes_referencia"] == date(2026, 7, 1)]
    assert sorted(x["roni"] for x in jja) == [1.36, 1.40]
    assert enso.checar_tabela(destino)["temporadas"] == 921


def test_arquivo_invalido_nao_grava_nada(tmp_path: Path) -> None:
    destino = tmp_path / "enso"
    with pytest.raises(enso.ChecagemError):
        enso.gravar(destino, "lixo", "https://noaa/RONI.ascii.txt", QUANDO)

    assert not DeltaTable.is_deltatable(str(destino / "resposta"))


def test_loader_sem_delta_cria_a_tabela_e_falha(tmp_path: Path) -> None:
    db = tmp_path / "x.duckdb"

    assert load_enso.main(["--db", str(db), "--delta-dir", str(tmp_path / "nada")]) == 1
    with duckdb.connect(str(db)) as conexao:
        assert conexao.execute("select count(*) from bronze.enso_roni").fetchone() == (0,)


def test_cadeia_ate_a_gold_com_intensidades_lags_e_publicacao(tmp_path: Path) -> None:
    destino, banco = tmp_path / "enso", tmp_path / "analitico.duckdb"
    enso.gravar(destino, TEXTO, "https://noaa/RONI.ascii.txt", QUANDO)
    revisado = TEXTO.replace("JJA  2026  1.36", "JJA  2026  1.40")
    enso.gravar(
        destino, revisado, "https://noaa/RONI.ascii.txt", datetime(2026, 11, 12, tzinfo=UTC)
    )
    assert load_enso.main(["--db", str(banco), "--delta-dir", str(destino)]) == 0

    resultado = subprocess.run(
        [
            sys.executable, "-c", "from dbt.cli.main import cli; cli()",
            "build",
            "--project-dir", str(RAIZ),
            "--profiles-dir", str(RAIZ),
            "--target-path", str(tmp_path / "dbt_target"),
            "--log-path", str(tmp_path / "dbt_logs"),
            # cautious: sem os testes de outros fatos que também usam a dim_calendario.
            "--indirect-selection", "cautious",
            "--select", "+fct_enso_mensal",
        ],
        env={**os.environ, "DBT_DUCKDB_PATH": str(banco)},
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    assert resultado.returncode == 0, resultado.stdout[-3000:]

    with duckdb.connect(str(banco), read_only=True) as con:
        total, primeiro, ultimo = con.execute(
            "select count(*), min(mes_referencia), max(mes_referencia) from gold.fct_enso_mensal"
        ).fetchone()
        set_2026 = con.execute(
            "select roni, mes_publicacao, fase_limiar, intensidade_el_nino, intensidade_la_nina, "
            "roni_t_menos_3, intensidade_el_nino_t_menos_12, intensidade_la_nina_t_menos_12 "
            "from gold.fct_enso_mensal where mes_referencia = date '2026-09-01'"
        ).fetchone()
        jan_1979 = con.execute(
            "select roni_t_menos_12 from gold.fct_enso_mensal "
            "where mes_referencia = date '1979-01-01'"
        ).fetchone()
        jul_2026 = con.execute(
            "select roni from gold.fct_enso_mensal where mes_referencia = date '2026-07-01'"
        ).fetchone()

    # Recortado à dim_calendario (IPCA, desde 1979), mas com os lags vindos de 1978.
    assert (total, primeiro, ultimo) == (573, date(1979, 1, 1), date(2026, 9, 1))
    assert jan_1979 == (Decimal("0.96"),)  # roni_t_menos_12 = DJF/1978
    # ASO/2026 = 1,97: El Niño com intensidade 1,47, publicado em novembro (usa outubro).
    assert set_2026[:5] == (Decimal("1.97"), date(2026, 11, 1), "el_nino", Decimal("1.47"), 0)
    assert set_2026[5] == Decimal("0.97")  # 3 meses antes: junho, MJJ/2026
    # 12 meses antes, ASO/2025 = -0,78: La Niña com intensidade 0,28 e nenhuma de El Niño.
    assert set_2026[6:] == (0, Decimal("0.28"))
    assert jul_2026 == (Decimal("1.40"),)  # a staging usa a revisão mais recente
