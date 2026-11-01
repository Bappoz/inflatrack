"""Bronze da Taxa Selic (API SGS série 11 - BACEN): ingestão e gravação em Delta Lake.

Ponto de entrada único para coleta e validação da Taxa Selic diária.
Grava duas tabelas Delta em ``data/parquet/selic/``:

    data/parquet/selic/resposta/   selic_resposta   uma linha por resposta com hash SHA-256
    data/parquet/selic/taxa_dia/   selic_taxa_dia   taxa diária e anualizada com PyArrow

Ambas as tabelas só acrescentam registros novos e são particionadas por ano.
Reexecutar a mesma janela é estritamente idempotente.
Zero escrita direta em DuckDB (feita exclusivamente por ``loaders/load_selic.py``).
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

from inflatrack.clients.selic_sgs import SGSClient, SGSError

logger = logging.getLogger("inflatrack.selic")

FONTE = "selic"
TABELA = "taxa_dia"
SERIE_SELIC = 11
DIRETORIO_PADRAO = Path("data/parquet/selic")
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

ESQUEMA_TAXA = pa.schema(
    [
        pa.field("data_referencia", pa.date32(), nullable=False),
        pa.field("taxa_dia_pct", pa.float64(), nullable=False),
        pa.field("taxa_anualizada_pct", pa.float64(), nullable=False),
        pa.field("ano", pa.int16(), nullable=False),
        pa.field("_id_resposta", pa.string(), nullable=False),
        pa.field("_fonte", pa.string(), nullable=False),
        pa.field("_requisicao", pa.string(), nullable=False),
        pa.field("_ingerido_em", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

CHAVE_TAXA = ("data_referencia", "taxa_dia_pct")


class ChecagemError(ValueError):
    """Dados fora da conformidade esperada da camada Bronze da Selic."""


@dataclass(frozen=True)
class Gravacao:
    id_resposta: str
    resposta_nova: bool
    linhas_lidas: int
    linhas_novas: int


def hash_do_corpo(corpo: str) -> str:
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()


def transformar(payload: list[dict[str, Any]] | dict[str, Any]) -> list[dict[str, Any]]:
    """Converte a resposta da API SGS em registros tipados de taxa."""
    if isinstance(payload, list):
        itens = payload
    elif (
        isinstance(payload, dict)
        and "conteudo" in payload
        and isinstance(payload["conteudo"], list)
    ):
        itens = payload["conteudo"]
    else:
        raise SGSError(f"formato inesperado de payload SGS: {type(payload)}")

    if not itens:
        raise SGSError("a API SGS não retornou observações da Selic")

    linhas: list[dict[str, Any]] = []
    obrigatorias = {"data", "valor"}

    for item in itens:
        if not isinstance(item, dict):
            raise SGSError("item da lista de taxas não é um dicionário")
        if not obrigatorias.issubset(item.keys()):
            raise SGSError("resposta da API SGS sem as colunas esperadas")

        data_str = str(item["data"]).strip()
        try:
            data_ref = datetime.strptime(data_str, "%d/%m/%Y").date()
        except ValueError as err:
            raise SGSError(f"data inválida no formato DD/MM/AAAA: {data_str!r}") from err

        valor_raw = item["valor"]
        try:
            taxa_dia = float(valor_raw)
        except (ValueError, TypeError) as err:
            raise SGSError(f"valor numérico inválido de taxa: {valor_raw!r}") from err

        taxa_anualizada = ((1.0 + (taxa_dia / 100.0)) ** 252 - 1.0) * 100.0

        linhas.append(
            {
                "data_referencia": data_ref,
                "taxa_dia_pct": taxa_dia,
                "taxa_anualizada_pct": taxa_anualizada,
                "ano": data_ref.year,
            }
        )

    return linhas


def checar(linhas: Iterable[dict[str, Any]]) -> None:
    """Valida integridade física e faixas realistas da Selic."""
    linhas_lista = list(linhas)
    if not linhas_lista:
        raise ChecagemError("conjunto vazio de taxas Selic")

    for i, linha in enumerate(linhas_lista):
        taxa = linha["taxa_dia_pct"]
        if taxa <= 0.0 or taxa > 1.0:
            raise ChecagemError(f"linha {i}: taxa fora da faixa válida 0..1% ao dia: {taxa}")

        ano = linha["ano"]
        if ano < 1986 or ano > 2100:
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
    """Grava a resposta e suas taxas no Delta Lake com deduplicação."""
    agora = ingerido_em or datetime.now(UTC)
    hash_resp = hash_do_corpo(corpo)
    id_resp = hash_resp

    dir_resposta = destino / "resposta"
    dir_taxa = destino / "taxa_dia"
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
    if DeltaTable.is_deltatable(dir_taxa):
        tab_taxa = DeltaTable(dir_taxa)
        colunas = list(CHAVE_TAXA)
        tabela_chaves = tab_taxa.to_pyarrow_table(columns=colunas)
        for i in range(tabela_chaves.num_rows):
            tupla = tuple(tabela_chaves.column(c)[i].as_py() for c in colunas)
            chaves_ja_gravadas.add(tupla)

    novas: list[dict[str, Any]] = []
    for linha in linhas:
        chave = tuple(linha[c] for c in CHAVE_TAXA)
        if chave not in chaves_ja_gravadas:
            novas.append(linha)
            chaves_ja_gravadas.add(chave)

    if novas:
        tab_pyarrow_novas = pa.Table.from_pylist(novas, schema=ESQUEMA_TAXA)
        write_deltalake(
            dir_taxa,
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
    """Busca taxas Selic na API SGS do BACEN e grava em Delta Lake."""
    cliente = SGSClient()
    de_str = de.strftime("%d/%m/%Y")
    ate_str = ate.strftime("%d/%m/%Y")
    req = f"bcdata.sgs.{SERIE_SELIC}(dataInicial='{de_str}',dataFinal='{ate_str}')"

    data = cliente.buscar_serie(SERIE_SELIC, de_str, ate_str)
    corpo = json.dumps(data, ensure_ascii=False)
    return gravar(destino, requisicao=req, corpo=corpo)


def importar(origem_raw: Path, destino: Path = DIRETORIO_PADRAO) -> int:
    """Importa arquivos brutos .json.gz legados para o Delta Lake."""
    arquivos = sorted(origem_raw.glob("selic_*.json.gz"))
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
    caminho_taxa = destino / "taxa_dia"

    if not DeltaTable.is_deltatable(caminho_resp):
        raise ChecagemError(f"tabela de respostas não encontrada em {caminho_resp}")
    if not DeltaTable.is_deltatable(caminho_taxa):
        raise ChecagemError(f"tabela de taxas não encontrada em {caminho_taxa}")

    tab_taxa = ds.dataset(caminho_taxa, format="parquet", partitioning="hive").to_table()
    linhas_taxa = tab_taxa.num_rows

    if linhas_taxa == 0:
        raise ChecagemError("tabela selic_taxa_dia vazia")

    taxas = tab_taxa.column("taxa_dia_pct").to_pylist()
    if any(t is None or t <= 0.0 or t > 1.0 for t in taxas):
        raise ChecagemError("taxa fora da faixa válida encontrada")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--de", default="2020-01-01", help="Data inicial AAAA-MM-DD")
    parser.add_argument("--ate", default=date.today().isoformat(), help="Data final AAAA-MM-DD")
    parser.add_argument(
        "--destino", default=str(DIRETORIO_PADRAO), help="Diretório de destino Delta"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    de = date.fromisoformat(args.de)
    ate = date.fromisoformat(args.ate)

    logger.info("Coletando taxas Selic de %s a %s...", de, ate)
    res = coletar(de, ate, Path(args.destino))
    logger.info("Selic Delta: %d lidas, %d novas", res.linhas_lidas, res.linhas_novas)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
