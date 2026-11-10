"""Bronze da Cesta Básica do PROCON: tabela de respostas e tabela extraída, em Delta.

Cada carga gera duas estruturas no Delta Lake:
    data/parquet/procon/resposta/      procon_resposta      uma linha por versão de arquivo/resposta
    data/parquet/procon/cesta_basica/  procon_cesta_basica  uma linha por cotação mensal de produto

Utiliza o helper comum `inflatrack.common.bronze`. A tabela extraída só acrescenta dados
inéditos através da chave composta (data_pesquisa, produto, praca, preco_medio).
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa

from inflatrack.clients import procon
from inflatrack.common import bronze

logger = logging.getLogger("inflatrack.bronze_procon")

FONTE = "procon"
DIRETORIO_PADRAO = "data/parquet/procon"
TABELA = "cesta_basica"

ESQUEMA_CESTA_BASICA = bronze.esquema_extraido(
    [
        pa.field("data_pesquisa", pa.date32(), nullable=False),
        pa.field("produto", pa.string(), nullable=False),
        pa.field("unidade", pa.string(), nullable=False),
        pa.field("preco_medio", pa.float64(), nullable=False),
        pa.field("preco_minimo", pa.float64()),
        pa.field("preco_maximo", pa.float64()),
        pa.field("praca", pa.string(), nullable=False),
        pa.field("codigo_subitem_ipca", pa.string()),
    ]
)

CHAVE = ("data_pesquisa", "produto", "praca", "preco_medio")


@dataclass(frozen=True)
class Gravacao:
    respostas_novas: int
    linhas_lidas: int
    linhas_novas: int


def promover_cesta_basica(
    conteudo: str,
    requisicao: str,
    destino: Path | str = DIRETORIO_PADRAO,
    ingerido_em: datetime | None = None,
) -> Gravacao:
    """Promove o conteúdo de um CSV do PROCON para a camada Bronze em Delta."""
    ingerido_em = ingerido_em or datetime.now(UTC)
    destino_path = Path(destino)

    resposta = bronze.Resposta(
        url=requisicao,
        status_http=200,
        tipo_conteudo="text/csv",
        corpo=conteudo,
    )
    id_resposta, nova_resposta = bronze.gravar_resposta(destino_path, FONTE, resposta, ingerido_em)

    linhas = procon.extrair_cesta_basica(conteudo)
    linhas_com_metadados = bronze.com_metadados(
        linhas,
        id_resposta=id_resposta,
        fonte=FONTE,
        requisicao=requisicao,
        ingerido_em=ingerido_em,
    )

    linhas_novas = bronze.acrescentar(
        destino_path,
        TABELA,
        linhas_com_metadados,
        ESQUEMA_CESTA_BASICA,
        CHAVE,
    )

    return Gravacao(
        respostas_novas=1 if nova_resposta else 0,
        linhas_lidas=len(linhas),
        linhas_novas=linhas_novas,
    )


def importar_arquivo(
    arquivo: Path,
    destino: Path | str = DIRETORIO_PADRAO,
) -> Gravacao:
    """Importa um arquivo CSV local para a Bronze."""
    if not arquivo.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {arquivo}")

    conteudo = arquivo.read_text(encoding="utf-8")
    return promover_cesta_basica(conteudo, requisicao=str(arquivo), destino=destino)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestão Bronze da Cesta Básica do PROCON")
    subparsers = parser.add_subparsers(dest="comando", required=True)

    parser_imp = subparsers.add_parser("importar", help="Importa um arquivo CSV para a Bronze")
    parser_imp.add_argument("arquivo", type=Path, help="Caminho do arquivo CSV")
    parser_imp.add_argument(
        "--destino", type=Path, default=Path(DIRETORIO_PADRAO), help="Diretório Delta Bronze"
    )

    args = parser.parse_args()
    if args.comando == "importar":
        resultado = importar_arquivo(args.arquivo, destino=args.destino)
        print(
            f"Importação concluída: {resultado.linhas_novas} linhas novas inseridas "
            f"de {resultado.linhas_lidas} lidas."
        )


if __name__ == "__main__":
    main()
