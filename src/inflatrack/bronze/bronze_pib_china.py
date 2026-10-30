"""Bronze do PIB da China (Banco Mundial): tabela de respostas e tabela extraída, em Delta.

Grava duas tabelas Delta em ``data/parquet/pib_china/``:

    data/parquet/pib_china/resposta/    pib_china_resposta   uma linha por resposta DIFERENTE
    data/parquet/pib_china/indicador/   pib_china_indicador  observações anuais em formato longo

``pib_china_resposta`` guarda o corpo JSON inteiro retornado pela API do Banco Mundial
(inclusive metadados de paginação) e substitui os arquivos de ``data/raw/pib_china/``.
``pib_china_indicador`` é a tabela analítica extraída, mantendo todas as colunas que a API manda
(indicador, ano, valor, country, unit, obs_status, decimal etc.). A junção/pivô para o formato
largo fica para o dbt na camada Silver (E3).

As duas tabelas só acrescentam registros novos. Reexecutar para o mesmo dado é idempotente
(0 linhas novas adicionadas).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.dataset as ds
from deltalake import DeltaTable, write_deltalake

logger = logging.getLogger("inflatrack.bronze_pib_china")

FONTE = "pib_china"
DIRETORIO_PADRAO = Path("data/parquet/pib_china")
RAW_DIR_PADRAO = Path("data/raw/pib_china")

API_URL = "https://api.worldbank.org/v2/country/CHN/indicator/{indicador}"
INDICADORES = {
    "crescimento": "NY.GDP.MKTP.KD.ZG",
    "pib_usd": "NY.GDP.MKTP.CD",
}

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

ESQUEMA_INDICADOR = pa.schema(
    [
        pa.field("indicador", pa.string(), nullable=False),
        pa.field("ano", pa.int16(), nullable=False),
        pa.field("valor", pa.float64(), nullable=True),
        pa.field("indicador_nome", pa.string(), nullable=True),
        pa.field("pais_id", pa.string(), nullable=True),
        pa.field("pais_nome", pa.string(), nullable=True),
        pa.field("pais_iso3", pa.string(), nullable=True),
        pa.field("unidade", pa.string(), nullable=True),
        pa.field("obs_status", pa.string(), nullable=True),
        pa.field("decimal", pa.int16(), nullable=True),
        pa.field("_id_resposta", pa.string(), nullable=False),
        pa.field("_fonte", pa.string(), nullable=False),
        pa.field("_requisicao", pa.string(), nullable=False),
        pa.field("_ingerido_em", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

CHAVE_INDICADOR = ("indicador", "ano", "valor")


class WorldBankError(ValueError):
    """Resposta inválida ou incompleta da API do Banco Mundial."""


class ChecagemError(ValueError):
    """Dados fora da conformidade esperada da camada Bronze."""


@dataclass(frozen=True)
class Gravacao:
    id_resposta: str
    resposta_nova: bool
    linhas_lidas: int
    linhas_novas: int


def hash_do_corpo(corpo: str) -> str:
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()


def transformar(payload: list | dict, indicador_padrao: str | None = None) -> list[dict]:
    """Extrai as observações em formato longo preservando todos os atributos originais."""
    if isinstance(payload, list):
        if len(payload) == 2 and isinstance(payload[1], list):
            observacoes = payload[1]
        elif len(payload) > 0 and isinstance(payload[0], dict) and "date" in payload[0]:
            observacoes = payload
        else:
            raise WorldBankError("formato de payload inválido ou sem observações")
    elif isinstance(payload, dict):
        raise WorldBankError("formato inesperado de resposta da API (esperado list)")
    else:
        raise WorldBankError(f"tipo de payload não reconhecido: {type(payload)}")

    linhas = []
    for item in observacoes:
        if not isinstance(item, dict):
            raise WorldBankError("item de observação inválido no payload")

        ano_str = item.get("date")
        if not isinstance(ano_str, str) or not ano_str.isdigit():
            raise WorldBankError(f"ano inválido: {ano_str!r}")
        ano = int(ano_str)

        val_raw = item.get("value")
        valor = float(val_raw) if val_raw is not None else None

        ind_info = item.get("indicator")
        if isinstance(ind_info, dict):
            codigo_ind = ind_info.get("id") or indicador_padrao
            nome_ind = ind_info.get("value")
        else:
            codigo_ind = indicador_padrao
            nome_ind = None

        if not codigo_ind:
            raise WorldBankError("código do indicador não identificado")

        pais_info = item.get("country")
        if isinstance(pais_info, dict):
            pais_id = pais_info.get("id")
            pais_nome = pais_info.get("value")
        else:
            pais_id = None
            pais_nome = None

        pais_iso3 = item.get("countryiso3code")
        unidade = item.get("unit") or None
        obs_status = item.get("obs_status") or None

        dec_raw = item.get("decimal")
        dec = int(dec_raw) if dec_raw is not None and str(dec_raw).isdigit() else None

        linhas.append(
            {
                "indicador": codigo_ind,
                "ano": ano,
                "valor": valor,
                "indicador_nome": nome_ind,
                "pais_id": pais_id,
                "pais_nome": pais_nome,
                "pais_iso3": pais_iso3,
                "unidade": unidade,
                "obs_status": obs_status,
                "decimal": dec,
            }
        )

    return linhas


def checar(linhas: list[dict], indicador: str | None = None) -> None:
    """Valida as regras de negócio e de qualidade da Bronze:

    - Não vazio;
    - (indicador, ano) único;
    - Volume entre 60 e 65 anos desde 1960;
    - Último ano anulável.
    """
    if not linhas:
        raise ChecagemError("resposta vazia ou sem observações")

    pares = [(linha["indicador"], linha["ano"]) for linha in linhas]
    if len(pares) != len(set(pares)):
        raise ChecagemError("duplicidade encontrada para o par (indicador, ano)")

    anos = [linha["ano"] for linha in linhas]
    min_ano, max_ano = min(anos), max(anos)
    if min_ano > 1965:
        raise ChecagemError(f"série histórica truncada: início em {min_ano} (esperado <= 1965)")

    if len(linhas) < 55:
        raise ChecagemError(f"volume abaixo do esperado: {len(linhas)} anos (esperado >= 55)")

    logger.debug(
        "checagem aprovada para %s: %d anos (%d a %d)",
        indicador or "linhas",
        len(linhas),
        min_ano,
        max_ano,
    )


def _caminho(destino: Path, tabela: str) -> str:
    return str(destino / tabela)


def gravar_resposta(
    destino: Path,
    *,
    requisicao: str,
    corpo: str,
    ingerido_em: datetime,
    status_http: int | None,
    tipo_conteudo: str | None,
) -> tuple[str, bool]:
    """Grava na tabela Delta ``pib_china_resposta`` garantindo unicidade por hash do corpo."""
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


def _chave(linha: dict) -> tuple:
    return tuple(linha[col] for col in CHAVE_INDICADOR)


def _chaves_existentes(caminho: str, indicadores: Iterable[str]) -> set[tuple]:
    if not DeltaTable.is_deltatable(caminho):
        return set()
    filtro = ds.field("indicador").isin(list(indicadores))
    tabela = (
        DeltaTable(caminho)
        .to_pyarrow_dataset()
        .to_table(columns=list(CHAVE_INDICADOR), filter=filtro)
    )
    colunas = [tabela.column(col).to_pylist() for col in CHAVE_INDICADOR]
    return set(zip(*colunas, strict=True))


def acrescentar_indicadores(destino: Path, linhas: list[dict]) -> int:
    """Acrescenta na tabela Delta ``pib_china_indicador`` apenas linhas novas."""
    if not linhas:
        return 0
    caminho = _caminho(destino, "indicador")
    indicadores = {linha["indicador"] for linha in linhas}
    existentes = _chaves_existentes(caminho, indicadores)
    novas = [linha for linha in linhas if _chave(linha) not in existentes]
    if novas:
        write_deltalake(
            caminho,
            pa.Table.from_pylist(novas, ESQUEMA_INDICADOR),
            mode="append",
            partition_by=["indicador"],
        )
    return len(novas)


def _com_metadados(
    linhas: list[dict], id_resposta: str, requisicao: str, ingerido_em: datetime
) -> list[dict]:
    metadados = {
        "_id_resposta": id_resposta,
        "_fonte": FONTE,
        "_requisicao": requisicao,
        "_ingerido_em": ingerido_em,
    }
    return [linha | metadados for linha in linhas]


def gravar(
    destino: Path,
    indicador: str,
    requisicao: str,
    corpo: str,
    status_http: int | None = 200,
    tipo_conteudo: str | None = "application/json",
    ingerido_em: datetime | None = None,
) -> Gravacao:
    """Grava a resposta e suas observações extraídas em Delta Lake."""
    ingerido_em = ingerido_em or datetime.now(UTC)
    payload = json.loads(corpo)
    linhas = transformar(payload, indicador_padrao=indicador)
    checar(linhas, indicador=indicador)

    id_resposta, nova = gravar_resposta(
        destino,
        requisicao=requisicao,
        corpo=corpo,
        ingerido_em=ingerido_em,
        status_http=status_http,
        tipo_conteudo=tipo_conteudo,
    )
    novas = acrescentar_indicadores(
        destino, _com_metadados(linhas, id_resposta, requisicao, ingerido_em)
    )
    return Gravacao(id_resposta, nova, len(linhas), novas)


def coletar_e_gravar(destino: Path = DIRETORIO_PADRAO) -> list[Gravacao]:
    """Executa a coleta de todos os indicadores diretamente da API do Banco Mundial."""
    resultados = []
    with httpx.Client(follow_redirects=True, timeout=30.0) as cliente:
        for nome_chave, codigo_ind in INDICADORES.items():
            url = API_URL.format(indicador=codigo_ind)
            params = {"format": "json", "per_page": 1000}
            logger.info("coletando indicador %s (%s)", nome_chave, codigo_ind)
            resposta = cliente.get(url, params=params)
            resposta.raise_for_status()

            req_completa = str(resposta.request.url)
            gravacao = gravar(
                destino=destino,
                indicador=codigo_ind,
                requisicao=req_completa,
                corpo=resposta.text,
                status_http=resposta.status_code,
                tipo_conteudo=resposta.headers.get("content-type"),
            )
            logger.info(
                "%s: resposta_nova=%s, lidas=%d, novas=%d",
                codigo_ind,
                gravacao.resposta_nova,
                gravacao.linhas_lidas,
                gravacao.linhas_novas,
            )
            resultados.append(gravacao)
    return resultados


def importar_raw(raw_dir: Path = RAW_DIR_PADRAO, destino: Path = DIRETORIO_PADRAO) -> int:
    """Importa arquivos .json.gz existentes de data/raw/pib_china/ para as tabelas Delta."""
    de_para = {
        "pib_china_crescimento.json.gz": INDICADORES["crescimento"],
        "pib_china_valor_usd.json.gz": INDICADORES["pib_usd"],
        f"{INDICADORES['crescimento']}.json.gz": INDICADORES["crescimento"],
        f"{INDICADORES['pib_usd']}.json.gz": INDICADORES["pib_usd"],
    }

    total_novas = 0
    for caminho in sorted(raw_dir.glob("*.json.gz")):
        codigo_ind = de_para.get(caminho.name)
        if not codigo_ind:
            logger.warning("arquivo raw ignorado (nome desconhecido): %s", caminho.name)
            continue

        with gzip.open(caminho, "rt", encoding="utf-8") as f:
            corpo = f.read()

        ingerido_em = datetime.fromtimestamp(caminho.stat().st_mtime, UTC)
        requisicao = API_URL.format(indicador=codigo_ind) + "?format=json&per_page=1000"

        logger.info("importando raw %s -> indicador %s", caminho.name, codigo_ind)
        gravacao = gravar(
            destino=destino,
            indicador=codigo_ind,
            requisicao=requisicao,
            corpo=corpo,
            status_http=None,
            tipo_conteudo="application/json",
            ingerido_em=ingerido_em,
        )
        logger.info(
            "importado %s: resposta_nova=%s, observacoes_novas=%d",
            caminho.name,
            gravacao.resposta_nova,
            gravacao.linhas_novas,
        )
        total_novas += gravacao.linhas_novas

    return total_novas


def checar_tabelas(destino: Path = DIRETORIO_PADRAO) -> None:
    """Verifica e relata o estado das tabelas Delta da Bronze do PIB da China."""
    caminho_resp = _caminho(destino, "resposta")
    caminho_ind = _caminho(destino, "indicador")

    if not DeltaTable.is_deltatable(caminho_resp):
        raise ChecagemError("tabela pib_china_resposta não existe ou não é Delta válida")
    if not DeltaTable.is_deltatable(caminho_ind):
        raise ChecagemError("tabela pib_china_indicador não existe ou não é Delta válida")

    dt_resp = DeltaTable(caminho_resp)
    dt_ind = DeltaTable(caminho_ind)

    linhas_resp = dt_resp.to_pyarrow_table().num_rows
    tabela_ind = dt_ind.to_pyarrow_table()
    linhas_ind = tabela_ind.num_rows

    print(f"=== pib_china_resposta (versão {dt_resp.version()}): {linhas_resp} linhas")
    print(f"=== pib_china_indicador (versão {dt_ind.version()}): {linhas_ind} linhas")

    df = tabela_ind.to_pandas()
    for ind, grupo in df.groupby("indicador"):
        anos = grupo["ano"].nunique()
        nulos = grupo["valor"].isna().sum()
        print(f"  * Indicador {ind}: {len(grupo)} linhas, {anos} anos distintos, {nulos} nulos")
        if anos != len(grupo):
            raise ChecagemError(f"Duplicidade de anos detectada no indicador {ind}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="comando")

    p_coletar = subparsers.add_parser("coletar", help="Coleta da API e grava nas tabelas Delta")
    p_coletar.add_argument("--destino", default=str(DIRETORIO_PADRAO))

    p_importar = subparsers.add_parser("importar", help="Importa raw existente para Delta")
    p_importar.add_argument("--raw-dir", default=str(RAW_DIR_PADRAO))
    p_importar.add_argument("--destino", default=str(DIRETORIO_PADRAO))

    p_checar = subparsers.add_parser("checar", help="Verifica integridade das tabelas Delta")
    p_checar.add_argument("--destino", default=str(DIRETORIO_PADRAO))

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.comando == "coletar" or args.comando is None:
        destino = Path(args.destino if hasattr(args, "destino") else DIRETORIO_PADRAO)
        coletar_e_gravar(destino)
    elif args.comando == "importar":
        importar_raw(Path(args.raw_dir), Path(args.destino))
    elif args.comando == "checar":
        checar_tabelas(Path(args.destino))

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
