"""Bronze do Dólar Comercial (API Olinda PTAX): tabela de respostas e tabela de boletins, em Delta.

Grava duas tabelas Delta em ``data/parquet/dolar/``:

    data/parquet/dolar/resposta/   dolar_resposta   uma linha por resposta DIFERENTE
    data/parquet/dolar/boletim/    dolar_boletim    todos os boletins intradiários

``dolar_resposta`` guarda o corpo JSON completo da resposta e substitui
arquivos de ``data/raw/bcb/``.
``dolar_boletim`` preserva todos os boletins publicados no período com tipagem estrita PyArrow,
permitindo tanto a escolha do fechamento quanto análises de volatilidade intradiária (consulta C10).
A imputação de calendário (*forward fill* com ``observado = false``) fica para a camada
Silver (E3 via dbt).

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

from inflatrack.dolar_olinda import OlindaClient, OlindaError

logger = logging.getLogger("inflatrack.bronze_dolar")

FONTE = "dolar"
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
            raise OlindaError(f"item inválido na lista de cotações: {item!r}")
        if not obrigatorias.issubset(item.keys()):
            raise OlindaError(f"item sem as colunas obrigatórias: {item.keys()}")

        data_hora_str = str(item["dataHoraCotacao"]).strip()
        try:
            # A API costuma devolver "AAAA-MM-DD HH:MM:SS.fff"
            data_hora = datetime.fromisoformat(data_hora_str)
        except ValueError as err:
            raise OlindaError(f"data_hora_cotacao inválida: {data_hora_str!r}") from err

        try:
            compra = float(item["cotacaoCompra"])
            venda = float(item["cotacaoVenda"])
        except (ValueError, TypeError) as err:
            raise OlindaError(f"cotação inválida em {item!r}") from err

        tipo_boletim = str(item.get("tipoBoletim") or "Único").strip()
        data_ref = data_hora.date()

        linhas.append(
            {
                "data_hora_cotacao": data_hora,
                "data_referencia": data_ref,
                "cotacao_compra": compra,
                "cotacao_venda": venda,
                "tipo_boletim": tipo_boletim,
                "ano": data_ref.year,
            }
        )

    return linhas


def checar(linhas: list[dict[str, Any]]) -> None:
    """Valida as regras de qualidade e sanidade da Bronze do Dólar:

    - Não vazio;
    - Cotações estritamente positivas;
    - Cotação de compra <= venda (spread);
    - Ao menos um boletim por dia útil presente.
    """
    if not linhas:
        raise ChecagemError("lista de boletins vazia")

    for linha in linhas:
        compra = linha["cotacao_compra"]
        venda = linha["cotacao_venda"]
        if compra <= 0 or venda <= 0:
            raise ChecagemError(f"cotação não positiva detectada: compra={compra}, venda={venda}")
        if compra > venda:
            raise ChecagemError(f"spread negativo detectado: compra={compra} > venda={venda}")

    dias_uteis = {
        linha["data_referencia"] for linha in linhas if linha["data_referencia"].weekday() < 5
    }
    if not dias_uteis:
        raise ChecagemError("nenhum boletim em dia útil encontrado na amostra")

    logger.debug(
        "checagem aprovada: %d boletins distribuídos em %d dias úteis", len(linhas), len(dias_uteis)
    )


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
    """Grava na tabela Delta ``dolar_resposta`` garantindo idempotência por hash do corpo."""
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
    return tuple(linha[col] for col in CHAVE_BOLETIM)


def _chaves_existentes(caminho: str, anos: Iterable[int]) -> set[tuple]:
    if not DeltaTable.is_deltatable(caminho):
        return set()
    filtro = ds.field("ano").isin(list(anos))
    tabela = (
        DeltaTable(caminho)
        .to_pyarrow_dataset()
        .to_table(columns=list(CHAVE_BOLETIM), filter=filtro)
    )
    colunas = [tabela.column(col).to_pylist() for col in CHAVE_BOLETIM]
    return set(zip(*colunas, strict=True))


def acrescentar_boletins(destino: Path, linhas: list[dict[str, Any]]) -> int:
    """Acrescenta na tabela Delta ``dolar_boletim`` apenas registros novos."""
    if not linhas:
        return 0
    caminho = _caminho(destino, "boletim")
    anos = {linha["ano"] for linha in linhas}
    existentes = _chaves_existentes(caminho, anos)
    novas = [linha for linha in linhas if _chave(linha) not in existentes]
    if novas:
        write_deltalake(
            caminho,
            pa.Table.from_pylist(novas, ESQUEMA_BOLETIM),
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
    """Grava resposta e boletins na camada Bronze em Delta Lake."""
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
    novas = acrescentar_boletins(destino, linhas_com_meta)
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
    cliente: OlindaClient | None = None,
) -> Gravacao:
    """Coleta o período solicitado na API Olinda e persiste na camada Bronze."""
    if de > ate:
        raise ValueError("'de' não pode ser maior que 'ate'")
    cli = cliente or OlindaClient()
    inicio_str = de.strftime("%m-%d-%Y")
    fim_str = ate.strftime("%m-%d-%Y")
    requisicao = f"CotacaoDolarPeriodo(dataInicial='{inicio_str}',dataFinalCotacao='{fim_str}')"
    dados = cli.buscar_dolar(inicio_str, fim_str)
    corpo = json.dumps({"value": dados}, ensure_ascii=False)
    resultado = gravar(destino, requisicao=requisicao, corpo=corpo)
    logger.info(
        "dolar (%s a %s): resposta_nova=%s, lidas=%d, novas=%d",
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

    arquivos = sorted(raw_dir.glob("dolar_*.json.gz"))
    total_importados = 0
    for arq in arquivos:
        logger.info("importando raw legado %s", arq.name)
        with gzip.open(arq, "rt", encoding="utf-8") as f:
            corpo = f.read()
        requisicao = f"raw_legado:{arq.name}"
        res = gravar(destino, requisicao=requisicao, corpo=corpo)
        total_importados += res.linhas_novas
        logger.info(
            "%s: resposta_nova=%s, observacoes_novas=%d",
            arq.name,
            res.resposta_nova,
            res.linhas_novas,
        )
    return total_importados


def checar_tabela(destino: Path = DIRETORIO_PADRAO) -> None:
    """Verifica volume, integridade e conformidade das tabelas Delta locais."""
    caminho_resp = _caminho(destino, "resposta")
    caminho_bol = _caminho(destino, "boletim")

    if not DeltaTable.is_deltatable(caminho_resp):
        raise ChecagemError(f"tabela de respostas não encontrada em {caminho_resp}")
    if not DeltaTable.is_deltatable(caminho_bol):
        raise ChecagemError(f"tabela de boletins não encontrada em {caminho_bol}")

    dt_resp = DeltaTable(caminho_resp)
    dt_bol = DeltaTable(caminho_bol)

    linhas_resp = dt_resp.to_pyarrow_table().num_rows
    tab_bol = dt_bol.to_pyarrow_table()
    linhas_bol = tab_bol.num_rows

    print(f"=== dolar_resposta: {linhas_resp} requisições gravadas")
    print(f"=== dolar_boletim: {linhas_bol} boletins no histórico")

    if linhas_bol == 0:
        raise ChecagemError("tabela dolar_boletim vazia")

    anos = sorted(set(tab_bol.column("ano").to_pylist()))
    print(f"  * Anos cobertos: {anos}")
    compra = tab_bol.column("cotacao_compra").to_pylist()
    venda = tab_bol.column("cotacao_venda").to_pylist()
    if any(c is None or c <= 0 for c in compra):
        raise ChecagemError("cotação de compra nula ou inválida encontrada")
    if any(v is None or v <= 0 for v in venda):
        raise ChecagemError("cotação de venda nula ou inválida encontrada")

    print("=== integridade da Bronze do Dólar aprovada com sucesso!")


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
