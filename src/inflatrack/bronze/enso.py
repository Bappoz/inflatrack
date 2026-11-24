"""Bronze do ENSO (El Niño / La Niña): o RONI do NOAA em Delta.

    data/parquet/enso/resposta/   enso_resposta  uma linha por resposta DIFERENTE (o .txt inteiro)
    data/parquet/enso/roni/       enso_roni      uma linha por versão de valor de temporada

O RONI vem como temporadas de 3 meses (DJF, JFM, ..., NDJ). Cada temporada é guardada no mês
central (DJF de 1950 -> jan/1950; NDJ de 1950 -> dez/1950). O valor de um mês central só sai
depois que o mês seguinte termina: o de setembro (ASO) usa outubro. Quem usa o RONI para prever
precisa respeitar isso (ver gold.fct_enso_mensal.mes_publicacao).

O NOAA revisa valores antigos quando recalcula a climatologia: a revisão entra como linha nova e a
anterior permanece; a staging usa a mais recente.

Uso::

    uv run python -m inflatrack.bronze.enso coletar
    uv run python -m inflatrack.bronze.enso checar
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as ds
from deltalake import DeltaTable, write_deltalake

from inflatrack.clients.noaa import NoaaClient, NoaaError

logger = logging.getLogger("inflatrack.enso")

FONTE = "enso"
DIRETORIO_PADRAO = "data/parquet/enso"
TIPO_TEXTO = "text/plain"

# Temporada -> mês central.
TEMPORADAS = {
    "DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
    "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12,
}  # fmt: skip
VOLUME_MINIMO = 900  # 1950 em diante: mais de 75 anos x 12 temporadas
FAIXA_RONI = (-4.0, 4.0)

ESQUEMA_RESPOSTA = pa.schema(
    [
        pa.field("id_resposta", pa.string(), nullable=False),
        pa.field("_fonte", pa.string(), nullable=False),
        pa.field("_requisicao", pa.string(), nullable=False),
        pa.field("_ingerido_em", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("status_http", pa.int16()),
        pa.field("tipo_conteudo", pa.string()),
        pa.field("corpo", pa.string(), nullable=False),
        pa.field("hash_corpo", pa.string(), nullable=False),
        pa.field("tamanho_bytes", pa.int64(), nullable=False),
    ]
)

ESQUEMA_RONI = pa.schema(
    [
        pa.field("id_leitura", pa.string(), nullable=False),
        pa.field("temporada", pa.string(), nullable=False),
        pa.field("ano", pa.int16(), nullable=False),
        pa.field("mes_referencia", pa.date32(), nullable=False),
        pa.field("roni", pa.float64(), nullable=False),
        pa.field("_id_resposta", pa.string(), nullable=False),
        pa.field("_fonte", pa.string(), nullable=False),
        pa.field("_requisicao", pa.string(), nullable=False),
        pa.field("_ingerido_em", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)


class ChecagemError(ValueError):
    """O arquivo do NOAA não tem a forma esperada e não deve ser promovido à Bronze."""


@dataclass(frozen=True)
class Gravacao:
    resposta_nova: bool
    linhas_lidas: int
    linhas_novas: int


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def transformar(texto: str) -> list[dict]:
    """Uma linha por temporada, no mês central. Linha fora do formato é erro, não é pulada."""
    linhas = [linha.split() for linha in texto.splitlines() if linha.strip()]
    if not linhas or [c.upper() for c in linhas[0]] != ["SEAS", "YR", "ANOM"]:
        raise ChecagemError("Cabeçalho do RONI diferente de 'SEAS YR ANOM'")
    registros = []
    for numero, campos in enumerate(linhas[1:], start=2):
        if len(campos) != 3 or campos[0] not in TEMPORADAS:
            raise ChecagemError(f"Linha {numero} do RONI fora do formato: {' '.join(campos)}")
        temporada, ano, valor = campos[0], int(campos[1]), float(campos[2])
        registros.append(
            {
                "temporada": temporada,
                "ano": ano,
                "mes_referencia": date(ano, TEMPORADAS[temporada], 1),
                "roni": valor,
            }
        )
    return registros


def checar(linhas: list[dict]) -> None:
    if len(linhas) < VOLUME_MINIMO:
        raise ChecagemError(f"RONI com {len(linhas)} temporadas (mínimo {VOLUME_MINIMO})")
    meses = [linha["mes_referencia"] for linha in linhas]
    if len(meses) != len(set(meses)):
        raise ChecagemError("RONI com mês central repetido")
    if meses != sorted(meses):
        raise ChecagemError("RONI fora de ordem cronológica")
    for anterior, atual in zip(meses, meses[1:], strict=False):
        if (atual.year - anterior.year) * 12 + atual.month - anterior.month != 1:
            raise ChecagemError(f"RONI com buraco entre {anterior} e {atual}")
    fora = [linha for linha in linhas if not FAIXA_RONI[0] <= linha["roni"] <= FAIXA_RONI[1]]
    if fora:
        raise ChecagemError(f"RONI fora da faixa {FAIXA_RONI}: {fora[:3]}")


def _acrescentar(caminho: str, linhas: list[dict], esquema: pa.Schema, chave: str) -> int:
    unicas = {linha[chave]: linha for linha in linhas}
    if DeltaTable.is_deltatable(caminho):
        existentes = (
            DeltaTable(caminho)
            .to_pyarrow_dataset()
            .to_table(columns=[chave], filter=ds.field(chave).isin(list(unicas)))
        )
        for valor in existentes.column(chave).to_pylist():
            unicas.pop(valor, None)
    if unicas:
        write_deltalake(
            caminho, pa.Table.from_pylist(list(unicas.values()), esquema), mode="append"
        )
    return len(unicas)


def gravar(
    destino: Path, texto: str, requisicao: str, ingerido_em: datetime | None = None
) -> Gravacao:
    """Valida o arquivo inteiro e grava resposta e temporadas novas (ou revisadas) em Delta."""
    linhas = transformar(texto)
    checar(linhas)
    ingerido_em = ingerido_em or datetime.now(UTC)
    id_resposta = _hash(texto)
    resposta = {
        "id_resposta": id_resposta,
        "_fonte": FONTE,
        "_requisicao": requisicao,
        "_ingerido_em": ingerido_em,
        "status_http": 200,
        "tipo_conteudo": TIPO_TEXTO,
        "corpo": texto,
        "hash_corpo": id_resposta,
        "tamanho_bytes": len(texto.encode("utf-8")),
    }
    resposta_nova = bool(
        _acrescentar(str(destino / "resposta"), [resposta], ESQUEMA_RESPOSTA, "hash_corpo")
    )
    metadados = {
        "_id_resposta": id_resposta,
        "_fonte": FONTE,
        "_requisicao": requisicao,
        "_ingerido_em": ingerido_em,
    }
    com_id = []
    for linha in linhas:
        conteudo = json.dumps(
            {"temporada": linha["temporada"], "ano": linha["ano"], "roni": linha["roni"]},
            sort_keys=True,
        )
        com_id.append(linha | metadados | {"id_leitura": _hash(conteudo)})
    novas = _acrescentar(str(destino / "roni"), com_id, ESQUEMA_RONI, "id_leitura")
    return Gravacao(resposta_nova, len(linhas), novas)


def coletar(cliente: NoaaClient, destino: Path = Path(DIRETORIO_PADRAO)) -> Gravacao:
    requisicao, texto = cliente.buscar_roni()
    grav = gravar(destino, texto, requisicao)
    logger.info(
        "RONI: resposta %s, %d de %d temporadas novas ou revisadas em %s",
        "nova" if grav.resposta_nova else "já guardada",
        grav.linhas_novas,
        grav.linhas_lidas,
        destino,
    )
    return grav


def checar_tabela(destino: Path) -> dict:
    caminho = str(destino / "roni")
    if not DeltaTable.is_deltatable(caminho):
        raise ChecagemError(f"Tabela Delta não encontrada em {caminho}")
    linhas = DeltaTable(caminho).to_pyarrow_table().to_pylist()
    ultima = {}
    for linha in sorted(linhas, key=lambda x: x["_ingerido_em"]):
        ultima[linha["mes_referencia"]] = linha
    vigentes = sorted(ultima.values(), key=lambda x: x["mes_referencia"])
    checar(vigentes)
    return {"temporadas": len(vigentes), "versoes": len(linhas), "ultimo": vigentes[-1]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="comando", required=True)
    for nome, ajuda in (("coletar", "Baixa o RONI do NOAA e grava em Delta"), ("checar", "")):
        sub = subparsers.add_parser(nome, help=ajuda or "Verifica a tabela Delta gravada")
        sub.add_argument("--destino", default=DIRETORIO_PADRAO)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    destino = Path(args.destino)
    try:
        if args.comando == "coletar":
            coletar(NoaaClient(), destino)
        else:
            info = checar_tabela(destino)
            ultimo = info["ultimo"]
            print(
                f"enso_roni temporadas={info['temporadas']} versoes={info['versoes']} "
                f"ultimo={ultimo['temporada']}/{ultimo['ano']}={ultimo['roni']} status=OK"
            )
        return 0
    except (NoaaError, ChecagemError) as erro:
        logger.error("RONI: %s", erro)
        return 1
    except Exception:
        logger.exception("Falha inesperada no RONI")
        return 1


if __name__ == "__main__":
    sys.exit(main())
