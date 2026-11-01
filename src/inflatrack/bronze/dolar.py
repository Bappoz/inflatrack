"""Bronze do Dólar Comercial (API Olinda PTAX): ingestão e gravação em Delta Lake.

Ponto de entrada único para coleta e validação das cotações do Dólar.
Grava duas tabelas Delta em ``data/parquet/dolar/``:

    data/parquet/dolar/resposta/   dolar_resposta   uma linha por resposta com hash SHA-256
    data/parquet/dolar/boletim/    dolar_boletim    todos os boletins intradiários com PyArrow

Ambas as tabelas só acrescentam registros novos e são particionadas por ano.
Reexecutar a mesma janela é estritamente idempotente.
Zero escrita direta em DuckDB (feita exclusivamente por ``loaders/load_dolar.py``).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.dataset as ds
from deltalake import DeltaTable, write_deltalake

from inflatrack.clients.dolar_olinda import OlindaClient, OlindaError

logger = logging.getLogger("inflatrack.dolar")

FONTE = "dolar"
TABELA = "boletim"
DIRETORIO_PADRAO = Path("data/parquet/dolar")
RAW_DIR_PADRAO = Path("data/raw/bcb")

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

ESQUEMA_BOLETIM = pa.schema(
    [
        pa.field("data_hora_cotacao", pa.timestamp("us"), nullable=False),
        pa.field("data_referencia", pa.date32(), nullable=False),
        pa.field("cotacao_compra", pa.float64(), nullable=False),
        pa.field("cotacao_venda", pa.float64(), nullable=False),
        pa.field("tipo_boletim", pa.string(), nullable=False),
        pa.field("ano", pa.int16(), nullable=False),
        pa.field("_id_resposta", pa.string(), nullable=False),
        pa.field("_fonte", pa.string(), nullable=False),
        pa.field("_requisicao", pa.string(), nullable=False),
        pa.field("_ingerido_em", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

CHAVE_BOLETIM = ("data_hora_cotacao", "tipo_boletim", "cotacao_compra", "cotacao_venda")


class ChecagemError(ValueError):
    """Dados fora da conformidade esperada da camada Bronze do Dólar."""


@dataclass(frozen=True)
class Gravacao:
    id_resposta: str
    resposta_nova: bool
    linhas_lidas: int
    linhas_novas: int


def hash_do_corpo(corpo: str) -> str:
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()


def transformar(payload: list[dict[str, Any]] | dict[str, Any]) -> list[dict[str, Any]]:
    """Converte a resposta OData da API Olinda em registros tipados de boletim.

    Preserva TODOS os boletins (abertura, intermediários e fechamento).
    """
    if isinstance(payload, dict):
        if "value" in payload and isinstance(payload["value"], list):
            itens = payload["value"]
        else:
            raise OlindaError("payload OData sem a chave 'value' esperada")
    elif isinstance(payload, list):
        itens = payload
    else:
        raise OlindaError(f"formato inesperado de payload: {type(payload)}")

    if not itens:
        raise OlindaError("a API Olinda não retornou cotações")

    linhas: list[dict[str, Any]] = []
    obrigatorias = {"cotacaoCompra", "cotacaoVenda", "dataHoraCotacao"}

    for item in itens:
        if not isinstance(item, dict):
            raise OlindaError("item da lista de cotações não é um dicionário")
        if not obrigatorias.issubset(item.keys()):
            raise OlindaError("resposta da API Olinda sem as colunas esperadas")

        instante_str = str(item["dataHoraCotacao"]).replace(" ", "T")
        instante = datetime.fromisoformat(instante_str)
        if instante.tzinfo is not None:
            instante = instante.astimezone(UTC).replace(tzinfo=None)

        compra = float(item["cotacaoCompra"])
        venda = float(item["cotacaoVenda"])
        tipo = str(item.get("tipoBoletim", "Desconhecido"))

        linhas.append(
            {
                "data_hora_cotacao": instante,
                "data_referencia": instante.date(),
                "cotacao_compra": compra,
                "cotacao_venda": venda,
                "tipo_boletim": tipo,
                "ano": instante.year,
            }
        )

    return linhas


def checar(linhas: Iterable[dict[str, Any]]) -> None:
    """Valida integridade física e de negócio mínima dos boletins."""
    linhas_lista = list(linhas)
    if not linhas_lista:
        raise ChecagemError("conjunto vazio de boletins")

    for i, linha in enumerate(linhas_lista):
        compra = linha["cotacao_compra"]
        venda = linha["cotacao_venda"]

        if compra <= 0 or venda <= 0:
            raise ChecagemError(
                f"linha {i}: cotação não positiva (compra={compra}, venda={venda})"
            )
        if venda < compra:
            raise ChecagemError(f"linha {i}: spread negativo (compra={compra}, venda={venda})")

        ano = linha["ano"]
        if ano < 1994 or ano > 2100:
            raise ChecagemError(f"linha {i}: ano implausível ({ano})")


def gravar(
    destino: Path,
    *,
    requisicao: str,
    corpo: str,
    status_http: int = 200,
    tipo_conteudo: str = "application/json",
    ingerido_em: datetime | None = None,
) -> Gravacao:
    """Grava a resposta e seus boletins no Delta Lake com deduplicação."""
    agora = ingerido_em or datetime.now(UTC)
    hash_resp = hash_do_corpo(corpo)
    id_resp = hash_resp

    dir_resposta = destino / "resposta"
    dir_boletim = destino / "boletim"
    dir_resposta.parent.mkdir(parents=True, exist_ok=True)

    resposta_nova = True
    if DeltaTable.is_deltatable(dir_resposta):
        tab_resp = DeltaTable(dir_resposta)
        col_hash = tab_resp.to_pyarrow_table(columns=["hash_corpo"]).column("hash_corpo")
        if hash_resp in col_hash.to_pylist():
            resposta_nova = False

    if resposta_nova:
        registro_resp = {
            "id_resposta": [id_resp],
            "_fonte": [FONTE],
            "_requisicao": [requisicao],
            "_ingerido_em": [agora],
            "status_http": [status_http],
            "tipo_conteudo": [tipo_conteudo],
            "corpo": [corpo],
            "hash_corpo": [hash_resp],
            "tamanho_bytes": [len(corpo.encode("utf-8"))],
        }
        tab_pyarrow_resp = pa.Table.from_pydict(registro_resp, schema=ESQUEMA_RESPOSTA)
        write_deltalake(dir_resposta, tab_pyarrow_resp, mode="append")

    payload = json.loads(corpo)
    linhas = transformar(payload)
    checar(linhas)

    for linha in linhas:
        linha["_id_resposta"] = id_resp
        linha["_fonte"] = FONTE
        linha["_requisicao"] = requisicao
        linha["_ingerido_em"] = agora

    chaves_ja_gravadas: set[tuple[Any, ...]] = set()
    if DeltaTable.is_deltatable(dir_boletim):
        tab_bol = DeltaTable(dir_boletim)
        colunas = list(CHAVE_BOLETIM)
        tabela_chaves = tab_bol.to_pyarrow_table(columns=colunas)
        for i in range(tabela_chaves.num_rows):
            tupla = tuple(tabela_chaves.column(c)[i].as_py() for c in colunas)
            chaves_ja_gravadas.add(tupla)

    novas: list[dict[str, Any]] = []
    for linha in linhas:
        chave = tuple(linha[c] for c in CHAVE_BOLETIM)
        if chave not in chaves_ja_gravadas:
            novas.append(linha)
            chaves_ja_gravadas.add(chave)

    if novas:
        tab_pyarrow_novas = pa.Table.from_pylist(novas, schema=ESQUEMA_BOLETIM)
        write_deltalake(
            dir_boletim,
            tab_pyarrow_novas,
            mode="append",
            partition_by=["ano"],
        )

    return Gravacao(
        id_resposta=id_resp,
        resposta_nova=resposta_nova,
        linhas_lidas=len(linhas),
        linhas_novas=len(novas),
    )


def coletar(de: date, ate: date, destino: Path = DIRETORIO_PADRAO) -> Gravacao:
    """Busca cotações na API Olinda PTAX e grava em Delta Lake."""
    cliente = OlindaClient()
    de_str = de.strftime("%m-%d-%Y")
    ate_str = ate.strftime("%m-%d-%Y")
    req = f"CotacaoDolarPeriodo(dataInicial='{de_str}',dataFinalCotacao='{ate_str}')"

    data = cliente.buscar_dolar(de_str, ate_str)
    corpo = json.dumps({"value": data}, ensure_ascii=False)
    return gravar(destino, requisicao=req, corpo=corpo)


def importar(origem_raw: Path, destino: Path = DIRETORIO_PADRAO) -> int:
    """Importa arquivos brutos .json.gz legados para o Delta Lake."""
    arquivos = sorted(origem_raw.glob("dolar_*.json.gz"))
    total_novas = 0
    for arq in arquivos:
        with gzip.open(arq, "rt", encoding="utf-8") as f:
            conteudo = f.read()
        res = gravar(destino, requisicao=f"arquivo:{arq.name}", corpo=conteudo)
        total_novas += res.linhas_novas
    return total_novas


def checar_tabela(destino: Path = DIRETORIO_PADRAO) -> None:
    """Verifica a integridade das tabelas Delta gravadas."""
    caminho_resp = destino / "resposta"
    caminho_bol = destino / "boletim"

    if not DeltaTable.is_deltatable(caminho_resp):
        raise ChecagemError(f"tabela de respostas não encontrada em {caminho_resp}")
    if not DeltaTable.is_deltatable(caminho_bol):
        raise ChecagemError(f"tabela de boletins não encontrada em {caminho_bol}")

    tab_bol = ds.dataset(caminho_bol, format="parquet", partitioning="hive").to_table()
    linhas_bol = tab_bol.num_rows

    if linhas_bol == 0:
        raise ChecagemError("tabela dolar_boletim vazia")

    compra = tab_bol.column("cotacao_compra").to_pylist()
    venda = tab_bol.column("cotacao_venda").to_pylist()
    if any(c is None or c <= 0 for c in compra):
        raise ChecagemError("cotação de compra nula ou inválida encontrada")
    if any(v is None or v <= 0 for v in venda):
        raise ChecagemError("cotação de venda nula ou inválida encontrada")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="comando")

    p_col = sub.add_parser("coletar", help="Coleta dados da API e grava em Delta")
    p_col.add_argument("--de", default="2020-01-01", help="Data inicial AAAA-MM-DD")
    p_col.add_argument("--ate", default=date.today().isoformat(), help="Data final AAAA-MM-DD")
    p_col.add_argument(
        "--destino", default=str(DIRETORIO_PADRAO), help="Diretório de destino Delta"
    )

    p_imp = sub.add_parser("importar", help="Importa arquivos .json.gz antigos")
    p_imp.add_argument("--raw-dir", default=str(RAW_DIR_PADRAO), help="Diretório de origem raw")
    p_imp.add_argument(
        "--destino", default=str(DIRETORIO_PADRAO), help="Diretório de destino Delta"
    )

    p_chk = sub.add_parser("checar", help="Valida estado das tabelas Delta")
    p_chk.add_argument(
        "--destino", default=str(DIRETORIO_PADRAO), help="Diretório de destino Delta"
    )

    args_list = list(argv) if argv is not None else sys.argv[1:]
    if not args_list or args_list[0] not in ("coletar", "importar", "checar", "-h", "--help"):
        args_list = ["coletar", *args_list]

    args = parser.parse_args(args_list)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.comando == "coletar":
        de = date.fromisoformat(args.de)
        ate = date.fromisoformat(args.ate)
        logger.info("Coletando cotações de dólar de %s a %s...", de, ate)
        res = coletar(de, ate, Path(args.destino))
        logger.info("Dólar Delta: %d lidas, %d novas", res.linhas_lidas, res.linhas_novas)
    elif args.comando == "importar":
        total = importar(Path(args.raw_dir), Path(args.destino))
        logger.info("Importação de raw legado do Dólar concluída: %d novas linhas", total)
    elif args.comando == "checar":
        checar_tabela(Path(args.destino))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
