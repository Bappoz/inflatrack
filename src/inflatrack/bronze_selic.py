"""Bronze da Taxa SELIC (Banco Central SGS Série 11): tabela de respostas e taxas diárias, em Delta.

Grava duas tabelas Delta em ``data/parquet/selic/``:

    data/parquet/selic/resposta/   selic_resposta   uma linha por resposta DIFERENTE da API
    data/parquet/selic/taxa_dia/   selic_taxa_dia   taxa diária apurada pelo BCB em dia útil

``selic_resposta`` guarda o corpo JSON retornado pela API e substitui arquivos de ``data/raw/bcb/``.
``selic_taxa_dia`` armazena a série 11 com tipagem estrita (data_referencia e taxa_dia_pct),
sem preenchimento de fins de semana e feriados (*forward fill*) na camada Bronze.
O preenchimento de calendário civil e alinhamento fica para a camada Silver (E3 via dbt).

Ambas as tabelas só acrescentam registros novos e são particionadas por ano.
Reexecutar a mesma janela é estritamente idempotente.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.dataset as ds
from deltalake import DeltaTable, write_deltalake

from inflatrack.selic_sgs import SGSClient, SGSError

logger = logging.getLogger("inflatrack.bronze_selic")

FONTE = "selic"
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

ESQUEMA_TAXA_DIA = pa.schema(
    [
        pa.field("data_referencia", pa.date32(), nullable=False),
        pa.field("taxa_dia_pct", pa.float64(), nullable=False),
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
    """Converte a resposta da API SGS em registros tipados de taxa diária.

    Mantém apenas os dias publicados pelo BCB, sem interpolação de calendário na Bronze.
    """
    if isinstance(payload, list):
        itens = payload
    elif (
        isinstance(payload, dict)
        and "conteudo" in payload
        and isinstance(payload["conteudo"], list)
    ):
        itens = payload["conteudo"]
    else:
        raise SGSError(f"formato inesperado de payload: {type(payload)}")

    if not itens:
        raise SGSError("a API SGS não retornou valores da Selic")

    linhas: list[dict[str, Any]] = []
    obrigatorias = {"data", "valor"}

    for item in itens:
        if not isinstance(item, dict):
            raise SGSError(f"item inválido na lista: {item!r}")
        if not obrigatorias.issubset(item.keys()):
            raise SGSError(f"item sem as chaves esperadas 'data' e 'valor': {item.keys()}")

        data_str = str(item["data"]).strip()
        try:
            # O SGS devolve datas no padrão DD/MM/AAAA
            data_ref = datetime.strptime(data_str, "%d/%m/%Y").date()
        except ValueError as err:
            raise SGSError(f"data inválida no formato DD/MM/AAAA: {data_str!r}") from err

        valor_raw = item["valor"]
        try:
            taxa = float(valor_raw)
        except (ValueError, TypeError) as err:
            raise SGSError(f"valor de taxa não numérico: {valor_raw!r}") from err

        linhas.append(
            {
                "data_referencia": data_ref,
                "taxa_dia_pct": taxa,
                "ano": data_ref.year,
            }
        )

    # Ordenar por data cronológica
    linhas.sort(key=lambda x: x["data_referencia"])
    return linhas


def checar(linhas: list[dict[str, Any]]) -> None:
    """Valida as regras de sanidade da Bronze da Selic:

    - Não vazio;
    - Unicidade por data_referencia;
    - Taxa na ordem de grandeza correta de taxa diária (0.0 < taxa < 1.0 % ao dia).
    """
    if not linhas:
        raise ChecagemError("lista de taxas vazia")

    datas = [linha["data_referencia"] for linha in linhas]
    if len(datas) != len(set(datas)):
        raise ChecagemError("duplicidade de data encontrada na amostra da Selic")

    for linha in linhas:
        taxa = linha["taxa_dia_pct"]
        if taxa <= 0.0 or taxa > 1.0:
            msg = f"taxa diária fora da faixa plausível: {taxa} em {linha['data_referencia']}"
            raise ChecagemError(msg)

    logger.debug("checagem aprovada: %d taxas diárias validadas", len(linhas))


def _caminho(destino: Path, tabela: str) -> str:
    return str(destino / tabela)


def gravar_resposta(
    destino: Path,
    *,
    requisicao: str,
    corpo: str,
    ingerido_em: datetime,
    status_http: int | None = 200,
    tipo_conteudo: str | None = "application/json",
) -> tuple[str, bool]:
    """Grava na tabela Delta ``selic_resposta`` garantindo idempotência por hash do corpo."""
    caminho = _caminho(destino, "resposta")
    id_resposta = hash_do_corpo(corpo)
    if DeltaTable.is_deltatable(caminho):
        existentes = (
            DeltaTable(caminho)
            .to_pyarrow_dataset()
            .to_table(columns=["hash_corpo"], filter=ds.field("hash_corpo") == id_resposta)
        )
        if existentes.num_rows > 0:
            return id_resposta, False

    linha = {
        "id_resposta": id_resposta,
        "_fonte": FONTE,
        "_requisicao": requisicao,
        "_ingerido_em": ingerido_em,
        "status_http": status_http,
        "tipo_conteudo": tipo_conteudo,
        "corpo": corpo,
        "hash_corpo": id_resposta,
        "tamanho_bytes": len(corpo.encode("utf-8")),
    }
    write_deltalake(caminho, pa.Table.from_pylist([linha], ESQUEMA_RESPOSTA), mode="append")
    return id_resposta, True


def _chave(linha: dict[str, Any]) -> tuple:
    return tuple(linha[col] for col in CHAVE_TAXA)


def _chaves_existentes(caminho: str, anos: Iterable[int]) -> set[tuple]:
    if not DeltaTable.is_deltatable(caminho):
        return set()
    filtro = ds.field("ano").isin(list(anos))
    tabela = (
        DeltaTable(caminho).to_pyarrow_dataset().to_table(columns=list(CHAVE_TAXA), filter=filtro)
    )
    colunas = [tabela.column(col).to_pylist() for col in CHAVE_TAXA]
    return set(zip(*colunas, strict=True))


def acrescentar_taxas(destino: Path, linhas: list[dict[str, Any]]) -> int:
    """Acrescenta na tabela Delta ``selic_taxa_dia`` apenas registros novos."""
    if not linhas:
        return 0
    caminho = _caminho(destino, "taxa_dia")
    anos = {linha["ano"] for linha in linhas}
    existentes = _chaves_existentes(caminho, anos)
    novas = [linha for linha in linhas if _chave(linha) not in existentes]
    if novas:
        write_deltalake(
            caminho,
            pa.Table.from_pylist(novas, ESQUEMA_TAXA_DIA),
            mode="append",
            partition_by=["ano"],
        )
    return len(novas)


def _com_metadados(
    linhas: list[dict[str, Any]], id_resposta: str, requisicao: str, ingerido_em: datetime
) -> list[dict[str, Any]]:
    metadados = {
        "_id_resposta": id_resposta,
        "_fonte": FONTE,
        "_requisicao": requisicao,
        "_ingerido_em": ingerido_em,
    }
    return [linha | metadados for linha in linhas]


def gravar(
    destino: Path,
    *,
    requisicao: str,
    corpo: str,
    status_http: int | None = 200,
    tipo_conteudo: str | None = "application/json",
    ingerido_em: datetime | None = None,
) -> Gravacao:
    """Grava resposta e taxas diárias na camada Bronze em Delta Lake."""
    agora = ingerido_em or datetime.now(tz=UTC)
    id_resposta, resposta_nova = gravar_resposta(
        destino,
        requisicao=requisicao,
        corpo=corpo,
        ingerido_em=agora,
        status_http=status_http,
        tipo_conteudo=tipo_conteudo,
    )
    payload = json.loads(corpo)
    linhas = transformar(payload)
    checar(linhas)
    linhas_com_meta = _com_metadados(linhas, id_resposta, requisicao, agora)
    novas = acrescentar_taxas(destino, linhas_com_meta)
    return Gravacao(
        id_resposta=id_resposta,
        resposta_nova=resposta_nova,
        linhas_lidas=len(linhas),
        linhas_novas=novas,
    )


def coletar(
    de: date,
    ate: date,
    destino: Path = DIRETORIO_PADRAO,
    cliente: SGSClient | None = None,
) -> Gravacao:
    """Coleta o período solicitado na API SGS e persiste na camada Bronze."""
    if de > ate:
        raise ValueError("'de' não pode ser maior que 'ate'")
    cli = cliente or SGSClient()
    inicio_str = de.strftime("%d/%m/%Y")
    fim_str = ate.strftime("%d/%m/%Y")
    requisicao = f"bcdata.sgs.11(dataInicial='{inicio_str}',dataFinal='{fim_str}')"
    dados = cli.buscar_serie(11, inicio_str, fim_str)
    corpo = json.dumps(dados, ensure_ascii=False)
    resultado = gravar(destino, requisicao=requisicao, corpo=corpo)
    logger.info(
        "selic (%s a %s): resposta_nova=%s, lidas=%d, novas=%d",
        de.isoformat(),
        ate.isoformat(),
        resultado.resposta_nova,
        resultado.linhas_lidas,
        resultado.linhas_novas,
    )
    return resultado


def importar(raw_dir: Path = RAW_DIR_PADRAO, destino: Path = DIRETORIO_PADRAO) -> int:
    """Importa arquivos .json.gz legados de data/raw/bcb/ para as tabelas Delta."""
    if not raw_dir.exists():
        logger.info("diretório de raw %s não existe; nada a importar", raw_dir)
        return 0

    arquivos = sorted(raw_dir.glob("selic_*.json.gz"))
    total_importados = 0
    for arq in arquivos:
        logger.info("importando raw legado %s", arq.name)
        with gzip.open(arq, "rt", encoding="utf-8") as f:
            corpo = f.read()
        requisicao = f"raw_legado:{arq.name}"
        res = gravar(destino, requisicao=requisicao, corpo=corpo)
        total_importados += res.linhas_novas
        logger.info(
            "%s: resposta_nova=%s, taxas_novas=%d", arq.name, res.resposta_nova, res.linhas_novas
        )
    return total_importados


def checar_tabela(destino: Path = DIRETORIO_PADRAO) -> None:
    """Verifica volume, integridade e conformidade das tabelas Delta locais da Selic."""
    caminho_resp = _caminho(destino, "resposta")
    caminho_taxa = _caminho(destino, "taxa_dia")

    if not DeltaTable.is_deltatable(caminho_resp):
        raise ChecagemError(f"tabela de respostas não encontrada em {caminho_resp}")
    if not DeltaTable.is_deltatable(caminho_taxa):
        raise ChecagemError(f"tabela de taxas não encontrada em {caminho_taxa}")

    dt_resp = DeltaTable(caminho_resp)
    dt_taxa = DeltaTable(caminho_taxa)

    linhas_resp = dt_resp.to_pyarrow_table().num_rows
    tab_taxa = dt_taxa.to_pyarrow_table()
    linhas_taxa = tab_taxa.num_rows

    print(f"=== selic_resposta: {linhas_resp} requisições gravadas")
    print(f"=== selic_taxa_dia: {linhas_taxa} observações no histórico")

    if linhas_taxa == 0:
        raise ChecagemError("tabela selic_taxa_dia vazia")

    anos = sorted(set(tab_taxa.column("ano").to_pylist()))
    print(f"  * Anos cobertos: {anos}")
    taxas = tab_taxa.column("taxa_dia_pct").to_pylist()
    if any(t is None or t <= 0.0 or t > 1.0 for t in taxas):
        raise ChecagemError("taxa fora da faixa válida encontrada")

    print("=== integridade da Bronze da Selic aprovada com sucesso!")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)

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

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.comando == "coletar":
        de = date.fromisoformat(args.de)
        ate = date.fromisoformat(args.ate)
        coletar(de, ate, Path(args.destino))
    elif args.comando == "importar":
        importar(Path(args.raw_dir), Path(args.destino))
    elif args.comando == "checar":
        checar_tabela(Path(args.destino))
    return 0


if __name__ == "__main__":
    sys.exit(main())
