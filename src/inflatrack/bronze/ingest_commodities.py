"""Ingestão das commodities da Alpha Vantage.

Cada resposta vai para a Bronze em Delta, em ``data/parquet/commodities/``::

    resposta/   commodities_resposta   uma linha por resposta DIFERENTE
    cotacao/    commodities_cotacao    uma linha por data da série, particionada por símbolo

A série chega inteira a cada chamada, então a partição do símbolo é **substituída**
quando a resposta muda, e fica como está quando a resposta é igual à já guardada. As
versões anteriores ficam na tabela de respostas.

Até a E3 continuam também o Raw em ``data/raw/commodities_raw/`` e o Parquet por
commodity na raiz de ``data/parquet/``, que ``load_commodities`` lê.

Uso::

    uv run python -m inflatrack.ingest_commodities --commodity ALL
    uv run python -m inflatrack.ingest_commodities importar   # Raw antigo -> Delta
    uv run python -m inflatrack.ingest_commodities checar
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
import pyarrow as pa
import requests
from deltalake import DeltaTable

from inflatrack import bronze
from inflatrack.alphavantage import AlphaVantageClient
from inflatrack.bronze import ChecagemError

logger = logging.getLogger(__name__)

FONTE = "commodities"
DIRETORIO_BRONZE = "data/parquet/commodities"
TABELA = "cotacao"

COMMODITY_CONFIGS = {
    "WTI": {
        "interval": "daily",
        "category": "Energia",
        "unit": "USD/barrel",
        "name": "Petróleo WTI",
    },
    "BRENT": {
        "interval": "daily",
        "category": "Energia",
        "unit": "USD/barrel",
        "name": "Petróleo Brent",
    },
    "NATURAL_GAS": {
        "interval": "daily",
        "category": "Energia",
        "unit": "USD/MMBtu",
        "name": "Gás Natural",
    },
    "WHEAT": {
        "interval": "monthly",
        "category": "Agrícola",
        "unit": "USD/metric ton",
        "name": "Trigo",
    },
    "CORN": {
        "interval": "monthly",
        "category": "Agrícola",
        "unit": "USD/metric ton",
        "name": "Milho",
    },
    "COTTON": {
        "interval": "monthly",
        "category": "Agrícola",
        "unit": "cents/pound",  # a API devolve "cents per pound" (conferido na Bronze)
        "name": "Algodão",
    },
    "SUGAR": {
        "interval": "monthly",
        "category": "Agrícola",
        "unit": "cents/pound",
        "name": "Açúcar",
    },
    "COFFEE": {
        "interval": "monthly",
        "category": "Agrícola",
        "unit": "cents/pound",
        "name": "Café",
    },
    "ALL_COMMODITIES": {
        "interval": "monthly",
        "category": "Geral",
        "unit": "index (2016=100)",
        "name": "Índice Global",
    },
}

# Linhas por série na resposta de 2026-09-28, contando as datas com ".". A série só
# cresce; menos linhas que isto indica resposta truncada ou histórico cortado na origem.
LINHAS_MINIMAS = {
    "WTI": 10_624,
    "BRENT": 10_265,
    "NATURAL_GAS": 7_751,
    "WHEAT": 559,
    "CORN": 559,
    "COTTON": 559,
    "SUGAR": 559,
    "COFFEE": 559,
    "ALL_COMMODITIES": 415,
}

MARCADOR_AUSENTE = "."

ESQUEMA_COTACAO = bronze.esquema_extraido(
    [
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("data_referencia", pa.date32(), nullable=False),
        pa.field("preco", pa.decimal128(28, 14)),
        pa.field("nome", pa.string(), nullable=False),
        pa.field("intervalo", pa.string(), nullable=False),
        pa.field("unidade", pa.string(), nullable=False),
    ]
)


@dataclass(frozen=True)
class Gravacao:
    symbol: str
    resposta_nova: bool
    linhas: int
    particao_substituida: bool


# --- Interpretação da resposta ------------------------------------------------------


def validar(symbol: str, dados: object) -> dict:
    """Recusa a resposta que não traz a série: cota esgotada, erro ou lista vazia.

    A Alpha Vantage responde 200 mesmo sem dados, com uma mensagem no lugar da série
    (``Information`` na cota esgotada, ``Error Message`` em parâmetro inválido).
    """
    if not isinstance(dados, dict):
        raise ChecagemError(f"{symbol}: resposta não é um objeto JSON")
    for campo in ("Information", "Note", "Error Message"):
        if campo in dados:
            raise ChecagemError(f"{symbol}: a API respondeu sem dados ({campo}): {dados[campo]}")
    if "data" not in dados:
        raise ChecagemError(f"{symbol}: campo 'data' ausente (campos: {sorted(dados)})")
    if not dados["data"]:
        raise ChecagemError(f"{symbol}: série vazia")
    esperado = COMMODITY_CONFIGS[symbol]["interval"]
    if dados.get("interval") != esperado:
        raise ChecagemError(f"{symbol}: intervalo {dados.get('interval')!r}, esperado {esperado!r}")
    return dados


def _preco(symbol: str, texto: str) -> Decimal | None:
    if texto == MARCADOR_AUSENTE:
        return None
    try:
        return Decimal(texto)
    except InvalidOperation as erro:
        raise ChecagemError(f"{symbol}: preço que não é número nem '.': {texto!r}") from erro


def transformar(symbol: str, dados: dict) -> list[dict]:
    """Uma linha por item de ``data``, inclusive as datas com ``"."`` (preço nulo)."""
    validar(symbol, dados)
    return [
        {
            "symbol": symbol,
            "data_referencia": date.fromisoformat(item["date"]),
            "preco": _preco(symbol, item["value"]),
            "nome": dados["name"],
            "intervalo": dados["interval"],
            "unidade": dados["unit"],
        }
        for item in dados["data"]
    ]


def checar(symbol: str, linhas: list[dict]) -> None:
    """Datas únicas e volume não menor que o de referência."""
    datas = [linha["data_referencia"] for linha in linhas]
    problemas = []
    if len(datas) != len(set(datas)):
        problemas.append(f"{len(datas) - len(set(datas))} datas repetidas")
    if len(linhas) < LINHAS_MINIMAS[symbol]:
        problemas.append(f"{len(linhas)} linhas (mínimo {LINHAS_MINIMAS[symbol]})")
    if all(linha["preco"] is None for linha in linhas):
        problemas.append("nenhum preço")
    if problemas:
        raise ChecagemError(f"{symbol}: " + "; ".join(problemas))


# --- Bronze --------------------------------------------------------------------------


def _id_da_particao(destino: Path, symbol: str) -> str | None:
    alvo = bronze.caminho(destino, TABELA)
    if not DeltaTable.is_deltatable(alvo):
        return None
    tabela = DeltaTable(alvo).to_pyarrow_table(
        columns=["_id_resposta"], partitions=[("symbol", "=", symbol)]
    )
    ids = set(tabela.column("_id_resposta").to_pylist())
    return ids.pop() if len(ids) == 1 else None


def gravar(
    destino: Path,
    symbol: str,
    resposta: bronze.Resposta,
    ingerido_em: datetime | None = None,
) -> Gravacao:
    """Checa e grava uma série nas duas tabelas. Nada é gravado se a checagem falhar."""
    ingerido_em = ingerido_em or datetime.now(UTC)
    try:
        dados = json.loads(resposta.corpo)
    except json.JSONDecodeError as erro:
        raise ChecagemError(f"{symbol}: corpo não é JSON: {resposta.corpo[:200]!r}") from erro
    linhas = transformar(symbol, dados)
    checar(symbol, linhas)

    id_resposta, nova = bronze.gravar_resposta(destino, FONTE, resposta, ingerido_em)
    if _id_da_particao(destino, symbol) == id_resposta:
        return Gravacao(symbol, nova, len(linhas), particao_substituida=False)
    bronze.substituir_particao(
        destino,
        TABELA,
        bronze.com_metadados(
            linhas,
            id_resposta=id_resposta,
            fonte=FONTE,
            requisicao=resposta.url,
            ingerido_em=ingerido_em,
        ),
        ESQUEMA_COTACAO,
        {"symbol": symbol},
    )
    return Gravacao(symbol, nova, len(linhas), particao_substituida=True)


def importar_raw(raw_dir: Path, destino: Path) -> list[Gravacao]:
    """Leva os ``<symbol>_historico.json.gz`` antigos para as duas tabelas.

    Como no IPCA: ``corpo`` é o JSON regravado pelo ingestor antigo, ``status_http`` e
    ``tipo_conteudo`` ficam nulos, ``_requisicao`` é reconstruída (sem a chave da API)
    e ``_ingerido_em`` é a data de modificação do arquivo.
    """
    gravacoes = []
    for symbol, config in COMMODITY_CONFIGS.items():
        arquivo = raw_dir / f"{symbol.lower()}_historico.json.gz"
        if not arquivo.is_file():
            logger.warning("%s: sem arquivo em %s", symbol, raw_dir)
            continue
        resposta = bronze.Resposta(
            AlphaVantageClient.url_publica(symbol, config["interval"]),
            None,
            None,
            bronze.ler_gz(arquivo),
        )
        ingerido_em = datetime.fromtimestamp(arquivo.stat().st_mtime, UTC)
        gravacoes.append(gravar(destino, symbol, resposta, ingerido_em))
    return gravacoes


def resumo_da_bronze(destino: Path) -> list[dict]:
    """Uma linha por símbolo: linhas, preços nulos, datas repetidas e período."""
    import duckdb

    cotacao = bronze.ler(destino, TABELA)  # noqa: F841 (lida pelo DuckDB)
    respostas = bronze.ler(destino, "resposta")  # noqa: F841
    linhas = duckdb.sql(
        """
        with por_requisicao as (
            select _requisicao, count(*) as respostas from respostas group by all
        )
        select symbol, count(*) as linhas,
               count(*) - count(distinct data_referencia) as datas_repetidas,
               count(*) filter (where preco is null) as sem_preco,
               count(*) filter (where preco <= 0) as preco_nao_positivo,
               min(data_referencia) as primeira_data, max(data_referencia) as ultima_data,
               coalesce(any_value(r.respostas), 0) as respostas_guardadas
        from cotacao c left join por_requisicao r using (_requisicao)
        group by symbol order by symbol
        """
    ).fetchall()
    colunas = [
        "symbol",
        "linhas",
        "datas_repetidas",
        "sem_preco",
        "preco_nao_positivo",
        "primeira_data",
        "ultima_data",
        "respostas_guardadas",
    ]
    return [dict(zip(colunas, linha, strict=True)) for linha in linhas]


# --- Caminho antigo (Raw + Parquet na raiz), mantido até a E3 ----------------------


def get_raw_dir():
    """Camada crua: resposta da API exatamente como veio (JSON gzip)."""
    raw_dir = Path(os.getcwd()) / "data" / "raw" / "commodities_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir


def get_parquet_dir():
    """Parquet pronto para carga no DuckDB por ``load_commodities``."""
    parquet_dir = Path(os.getcwd()) / "data" / "parquet"
    parquet_dir.mkdir(parents=True, exist_ok=True)
    return parquet_dir


def gravar_bruto(symbol: str, modo: str, data: dict) -> Path:
    """Congela a resposta da API em gzip, antes de qualquer transformação."""
    caminho = get_raw_dir() / f"{symbol.lower()}_{modo}.json.gz"
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        json.dump(data, arquivo, ensure_ascii=False)
    return caminho


def process_response(symbol: str, data: dict) -> pd.DataFrame:
    """Formato antigo do Parquet: só ``(symbol, data_referencia, preco)``, sem ``"."``."""
    validar(symbol, data)
    df = pd.DataFrame([r for r in data["data"] if r["value"] != MARCADOR_AUSENTE])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["value"] = df["value"].astype(float)
    df["symbol"] = symbol
    df = df.rename(columns={"date": "data_referencia", "value": "preco"})
    return df[["symbol", "data_referencia", "preco"]]


# --- Execução ------------------------------------------------------------------------


def ingest_commodity(
    client: AlphaVantageClient, symbol: str, modo: str, destino: Path | None = None
) -> Gravacao:
    """Busca uma commodity e grava a Bronze, o Raw e o Parquet antigo.

    Qualquer problema (HTTP, cota esgotada, série vazia, checagem) levanta exceção e
    nada é gravado para o símbolo.
    """
    config = COMMODITY_CONFIGS.get(symbol)
    if not config:
        raise ValueError(f"Commodity {symbol} não configurada.")

    logger.info(f"Iniciando ingestão de {symbol} no modo {modo}")
    resposta = client.buscar_resposta(function=symbol, interval=config["interval"])
    gravacao = gravar(Path(destino or DIRETORIO_BRONZE), symbol, resposta)

    dados = json.loads(resposta.corpo)
    logger.info(f"Resposta crua salva em {gravar_bruto(symbol, modo, dados)}")
    df = process_response(symbol, dados)
    output_file = get_parquet_dir() / f"{symbol.lower()}_{modo}.parquet"
    df.to_parquet(output_file, index=False)
    logger.info(
        "%s: %d linhas; resposta %s; partição %s; %d registros em %s",
        symbol,
        gravacao.linhas,
        "nova" if gravacao.resposta_nova else "já guardada",
        "substituída" if gravacao.particao_substituida else "mantida",
        len(df),
        output_file,
    )
    return gravacao


def _comando_ingerir(args: argparse.Namespace) -> int:
    client = AlphaVantageClient()
    if not getattr(client, "api_key", True):
        logger.error("ALPHAVANTAGE_API_KEY vazia: copie .env.example para .env e preencha a chave")
        return 1
    symbols = list(COMMODITY_CONFIGS) if args.commodity in (None, "ALL") else [args.commodity]
    falhas = []
    for symbol in symbols:
        try:
            ingest_commodity(client, symbol, args.modo, Path(args.parquet_dir))
        except (ChecagemError, requests.RequestException) as erro:
            logger.error("%s", erro)
            falhas.append(symbol)
            # Cota esgotada vale para todas as séries seguintes: não gaste mais pedidos.
            if isinstance(erro, ChecagemError) and (
                "(Information)" in str(erro) or "(Note)" in str(erro)
            ):
                break
    if falhas:
        logger.error("commodities sem ingestão: %s", ", ".join(falhas))
        return 1
    return 0


def _comando_importar(args: argparse.Namespace) -> int:
    for gravacao in importar_raw(Path(args.raw_dir), Path(args.parquet_dir)):
        logger.info(
            "%s: %d linhas; resposta %s",
            gravacao.symbol,
            gravacao.linhas,
            "nova" if gravacao.resposta_nova else "já guardada",
        )
    return 0


def _comando_checar(args: argparse.Namespace) -> int:
    resumo = resumo_da_bronze(Path(args.parquet_dir))
    for linha in resumo:
        print(" ".join(f"{coluna}={valor}" for coluna, valor in linha.items()))
    print(f"symbols={len(resumo)} linhas={sum(linha['linhas'] for linha in resumo)}")
    reprovado = len(resumo) != len(COMMODITY_CONFIGS) or any(
        linha["datas_repetidas"] or linha["linhas"] < LINHAS_MINIMAS[linha["symbol"]]
        for linha in resumo
    )
    return 1 if reprovado else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingestão de Commodities da Alpha Vantage")
    parser.add_argument("--parquet-dir", default=DIRETORIO_BRONZE, help="pasta da Bronze")
    parser.add_argument("--commodity", type=str, help="Symbol da commodity ou 'ALL' para todas")
    parser.add_argument("--modo", choices=["historico", "incremental"], default="historico")
    comandos = parser.add_subparsers(dest="comando")

    importar = comandos.add_parser("importar", help="leva data/raw/commodities_raw/ ao Delta")
    importar.add_argument("--raw-dir", default="data/raw/commodities_raw")
    importar.set_defaults(funcao=_comando_importar)

    checar_cmd = comandos.add_parser("checar", help="símbolos, volume e datas repetidas")
    checar_cmd.set_defaults(funcao=_comando_checar)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    funcao = getattr(args, "funcao", None) if args.comando else _comando_ingerir
    try:
        return funcao(args)
    except ChecagemError as erro:
        logger.error("%s", erro)
        return 1


if __name__ == "__main__":
    sys.exit(main())
