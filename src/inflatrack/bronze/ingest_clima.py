"""Ingestão do catálogo de estações e das medições diárias do INMET em Delta."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from inflatrack import bronze_clima
from inflatrack.inmet import (
    InmetClient,
    InmetError,
    transformar_estacoes,
)

logger = logging.getLogger("inflatrack.ingest_clima")

DELTA_DIR_PADRAO = Path("data/parquet/clima")


def processar_estacoes(
    cliente: InmetClient,
    delta_dir: Path = DELTA_DIR_PADRAO,
) -> pd.DataFrame:
    """Coleta e grava o catálogo de estações na Bronze Delta."""
    logger.info("Consultando catálogo de estações ativas do INMET...")
    payload = cliente.listar_estacoes(tipo="T")
    grav = bronze_clima.gravar(delta_dir, payload)
    logger.info(
        "Bronze Delta: resposta %s, %d de %d estações novas em %s",
        "nova" if grav.resposta_nova else "já guardada",
        grav.linhas_novas,
        grav.linhas_lidas,
        delta_dir,
    )

    return transformar_estacoes(payload)


def processar_medicoes(
    cliente: InmetClient,
    estacoes: list[str],
    data_inicio: str,
    data_fim: str,
    delta_dir: Path = DELTA_DIR_PADRAO,
) -> tuple[int, int]:
    """Busca cada estação indicada e grava as respostas e leituras em Delta."""
    inicio = pd.Timestamp(data_inicio).date()
    fim = pd.Timestamp(data_fim).date()
    if inicio > fim:
        raise ValueError("A data inicial deve ser anterior ou igual à data final.")
    if not estacoes:
        raise ValueError("Informe ao menos uma estação para coletar medições.")

    respostas_novas = medicoes_novas = 0
    for estacao_id in estacoes:
        endpoint = f"{data_inicio}/{data_fim}/{estacao_id}"
        payload = cliente.buscar_dados_estacao(estacao_id, data_inicio, data_fim)
        if not payload:
            logger.info("Nenhuma medição retornada para a estação %s", estacao_id)
            continue
        grav = bronze_clima.gravar_medicoes(
            delta_dir,
            payload,
            requisicao=f"{bronze_clima.BASE_URL}/estacao/diaria/{endpoint}",
        )
        respostas_novas += int(grav.resposta_nova)
        medicoes_novas += grav.linhas_novas
        logger.info(
            "Estação %s: %d leituras novas de %d recebidas",
            estacao_id,
            grav.linhas_novas,
            grav.linhas_lidas,
        )
    return respostas_novas, medicoes_novas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delta-dir", default=str(DELTA_DIR_PADRAO))
    parser.add_argument(
        "--apenas-estacoes",
        action="store_true",
        help="Sincroniza apenas o cadastro de estações meteorológicas",
    )
    parser.add_argument(
        "--medicoes",
        action="store_true",
        help="Busca medições diárias das estações informadas",
    )
    parser.add_argument("--estacao", action="append", default=[], help="ID INMET; pode repetir")
    parser.add_argument("--de", dest="data_inicio", help="Data inicial no formato AAAA-MM-DD")
    parser.add_argument("--ate", dest="data_fim", help="Data final no formato AAAA-MM-DD")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cliente = InmetClient()

    try:
        processar_estacoes(
            cliente,
            delta_dir=Path(args.delta_dir),
        )
        if args.medicoes:
            if not args.data_inicio or not args.data_fim:
                parser.error("--medicoes exige --de e --ate")
            respostas, leituras = processar_medicoes(
                cliente,
                args.estacao,
                args.data_inicio,
                args.data_fim,
                delta_dir=Path(args.delta_dir),
            )
            logger.info(
                "Bronze diária: %d respostas novas, %d medições novas",
                respostas,
                leituras,
            )
        return 0
    except (InmetError, bronze_clima.ChecagemError) as exc:
        logger.error("Erro na API do INMET: %s", exc)
        return 1
    except Exception as exc:
        logger.exception("Falha inesperada na ingestão do clima: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
