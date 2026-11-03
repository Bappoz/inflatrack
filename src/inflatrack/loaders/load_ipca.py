"""Carga da Bronze Delta do IPCA/INPC no DuckDB analítico compartilhado.

``data/parquet/ipca/observacao/`` vira ``bronze.ipca_observacao`` e ``data/parquet/ipca/metadados/``
vira ``bronze.ipca_metadados``, sem nenhuma regra de negócio. As tabelas são criadas na primeira
carga com o esquema do próprio Delta (``bronze.carregar_duckdb``), sem ``setup_duckdb_*.sql``.

Só acrescenta, como o Delta: a revisão do IBGE chega como linha nova (o valor está na chave), e
rodar de novo não duplica. Escolher a versão mais recente é trabalho da Silver
(``stg_ipca__observacao``), não da carga.

Uso::

    uv run python -m inflatrack.loaders.load_ipca
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
from deltalake import DeltaTable

from inflatrack.bronze import ipca
from inflatrack.common import bronze
from inflatrack.common.db import DUCKDB_PADRAO

logger = logging.getLogger("inflatrack.load_ipca")

DELTA_PADRAO = Path(ipca.DIRETORIO_PADRAO)

# O agregado entra na chave porque ``CHAVE_OBSERVACAO`` só é única dentro de um agregado: o 1737
# e o 7060 publicam o mesmo índice geral. Tabela do Delta -> (tabela do DuckDB, chave).
TABELAS = {
    "observacao": ("bronze.ipca_observacao", ("agregado", *ipca.CHAVE_OBSERVACAO)),
    "metadados": ("bronze.ipca_metadados", ipca.CHAVE_METADADOS),
}


def carregar(conexao: duckdb.DuckDBPyConnection, delta_dir: Path) -> dict[str, int]:
    """Espelha as duas tabelas Delta no DuckDB. Devolve as linhas inseridas por tabela."""
    conexao.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    inseridas = {}
    for origem, (destino, chave) in TABELAS.items():
        caminho = bronze.caminho(delta_dir, origem)
        if not DeltaTable.is_deltatable(caminho):
            raise FileNotFoundError(f"Tabela Delta do IPCA não encontrada em {caminho}")
        dataset = DeltaTable(caminho).to_pyarrow_dataset()
        inseridas[destino] = bronze.carregar_duckdb(conexao, dataset, destino, "acrescenta", chave)
    return inseridas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=str(DUCKDB_PADRAO), help="Caminho do banco DuckDB")
    parser.add_argument(
        "--delta-dir", default=str(DELTA_PADRAO), help="Diretório da Bronze Delta do IPCA"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)

    try:
        with duckdb.connect(str(db)) as conexao:
            inseridas = carregar(conexao, Path(args.delta_dir))
            for tabela, novas in inseridas.items():
                total = conexao.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]
                logger.info("%s: %d linhas novas, %d no total", tabela, novas, total)
    except FileNotFoundError as erro:
        logger.error("%s — rode `just bronze-ipca-metadados` ou a carga do IPCA antes", erro)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
