"""Bronze do PIB Internacional (China, EUA e Rússia) via Banco Mundial em Delta Lake.

Unifica a ingestão e armazenamento das séries históricas de PIB dos países parceiros
econômicos relevantes:
  - China (CHN)
  - Estados Unidos (USA)
  - Rússia (RUS)

Grava duas tabelas Delta por país em ``data/parquet/pib_<pais>/``:
  - resposta/   tabela de respostas HTTP imutáveis (uma linha por resposta diferente)
  - indicador/  tabela de observações anuais extraídas em formato longo

As tabelas Delta acrescentam registros novos e garantem idempotência em execuções repetidas.
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

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
from deltalake import DeltaTable, write_deltalake

from inflatrack.clients.worldbank import (
    INDICADOR_CRESCIMENTO,
    INDICADOR_PIB_USD,
    INDICADORES,
    PAISES,
    WorldBankClient,
    WorldBankError,
)
from inflatrack.common.bronze import ESQUEMA_RESPOSTA

logger = logging.getLogger("inflatrack.bronze_pib_internacional")

PAISES_PADRAO = tuple(PAISES.keys())
CHAVE_INDICADOR = ("indicador", "ano", "valor")

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


MAPA_PAIS_FONTE = {
    "CHN": "china",
    "USA": "usa",
    "RUS": "russia",
}


def sufixo_pais(pais: str) -> str:
    pais_upper = pais.upper()
    return MAPA_PAIS_FONTE.get(pais_upper, pais_upper.lower())


def diretorio_padrao_pais(pais: str) -> Path:
    return Path(f"data/parquet/pib_{sufixo_pais(pais)}")


def raw_dir_padrao_pais(pais: str) -> Path:
    return Path(f"data/raw/pib_{sufixo_pais(pais)}")


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


def transformar_largo(payload_crescimento: list, payload_pib_usd: list) -> pd.DataFrame:
    """Combina as duas séries anuais em formato largo (ano, crescimento_pib_pct, pib_usd)."""
    valores: dict[int, dict[str, float | int | None]] = {}

    for payload, coluna in (
        (payload_crescimento, "crescimento_pib_pct"),
        (payload_pib_usd, "pib_usd"),
    ):
        if len(payload) < 2 or not isinstance(payload[1], list):
            raise WorldBankError(f"payload inválido para {coluna}")
        for item in payload[1]:
            if not isinstance(item, dict):
                raise WorldBankError(f"observação inválida para {coluna}")
            ano_texto = item.get("date")
            if not isinstance(ano_texto, str) or not ano_texto.isdigit():
                raise WorldBankError(f"ano inválido para {coluna}: {ano_texto!r}")
            ano = int(ano_texto)
            valor = item.get("value")
            valores.setdefault(ano, {"ano": ano})[coluna] = (
                float(valor) if valor is not None else None
            )

    quadro = pd.DataFrame(valores.values(), columns=["ano", "crescimento_pib_pct", "pib_usd"])
    if quadro.empty:
        raise WorldBankError("a API não retornou observações")
    return quadro.sort_values("ano", ignore_index=True)


def executar_ingestao_larga(
    pais: str,
    raw_dir: Path | None = None,
    parquet_dir: Path | None = None,
    cliente: WorldBankClient | None = None,
) -> int:
    """Ingestão e materialização do Parquet anual no formato largo legado."""
    pais_upper = pais.upper()
    raw_dir = raw_dir or raw_dir_padrao_pais(pais_upper)
    parquet_dir = parquet_dir or diretorio_padrao_pais(pais_upper)

    def _executar(wb: WorldBankClient) -> int:
        logger.info("coletando crescimento anual do PIB de %s", pais_upper)
        payload_crescimento = wb.buscar_payload(pais_upper, INDICADOR_CRESCIMENTO)
        raw_dir.mkdir(parents=True, exist_ok=True)
        with gzip.open(raw_dir / f"{INDICADOR_CRESCIMENTO}.json.gz", "wt", encoding="utf-8") as f:
            json.dump(payload_crescimento, f, ensure_ascii=False)

        logger.info("coletando PIB nominal anual de %s em USD", pais_upper)
        payload_pib_usd = wb.buscar_payload(pais_upper, INDICADOR_PIB_USD)
        with gzip.open(raw_dir / f"{INDICADOR_PIB_USD}.json.gz", "wt", encoding="utf-8") as f:
            json.dump(payload_pib_usd, f, ensure_ascii=False)

        quadro = transformar_largo(payload_crescimento, payload_pib_usd)
        parquet_dir.mkdir(parents=True, exist_ok=True)
        destino = parquet_dir / f"pib_{sufixo_pais(pais_upper)}.parquet"
        quadro.to_parquet(destino, index=False)
        logger.info("%d anos transformados em %s", len(quadro), destino)
        return len(quadro)

    if cliente:
        return _executar(cliente)
    with WorldBankClient() as wb:
        return _executar(wb)


def checar(linhas: list[dict], pais: str = "CHN", indicador: str | None = None) -> None:
    """Valida as regras de negócio e integridade da Bronze para o país especificado."""
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

    # Regra específica para a Rússia: aceita nulos pré-1990, mas exige integridade pós-1990
    if pais.upper() == "RUS":
        pos_1990 = [item for item in linhas if item["ano"] >= 1990 and item["valor"] is not None]
        if len(pos_1990) < 30:
            raise ChecagemError(f"volume pós-1990 insuficiente na Rússia: {len(pos_1990)} anos")

    logger.debug(
        "checagem aprovada para %s (%s): %d anos (%d a %d)",
        indicador or "linhas",
        pais.upper(),
        len(linhas),
        min_ano,
        max_ano,
    )


def _caminho(destino: Path, tabela: str) -> str:
    return str(destino / tabela)


def gravar_resposta(
    destino: Path,
    *,
    fonte: str,
    requisicao: str,
    corpo: str,
    ingerido_em: datetime,
    status_http: int | None,
    tipo_conteudo: str | None,
) -> tuple[str, bool]:
    """Grava na tabela Delta ``<fonte>_resposta`` garantindo unicidade por hash do corpo."""
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
        "_fonte": fonte,
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
    """Acrescenta na tabela Delta ``indicador`` apenas registros inéditos."""
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
    linhas: list[dict], fonte: str, id_resposta: str, requisicao: str, ingerido_em: datetime
) -> list[dict]:
    metadados = {
        "_id_resposta": id_resposta,
        "_fonte": fonte,
        "_requisicao": requisicao,
        "_ingerido_em": ingerido_em,
    }
    return [linha | metadados for linha in linhas]


def gravar(
    destino: Path,
    indicador: str,
    requisicao: str,
    corpo: str,
    pais: str = "CHN",
    status_http: int | None = 200,
    tipo_conteudo: str | None = "application/json",
    ingerido_em: datetime | None = None,
) -> Gravacao:
    """Valida e grava a resposta e as observações extraídas nas tabelas Delta."""
    fonte = f"pib_{sufixo_pais(pais)}"
    ingerido_em = ingerido_em or datetime.now(UTC)
    payload = json.loads(corpo)
    linhas = transformar(payload, indicador_padrao=indicador)
    checar(linhas, pais=pais, indicador=indicador)

    id_resposta, nova = gravar_resposta(
        destino,
        fonte=fonte,
        requisicao=requisicao,
        corpo=corpo,
        ingerido_em=ingerido_em,
        status_http=status_http,
        tipo_conteudo=tipo_conteudo,
    )
    novas = acrescentar_indicadores(
        destino, _com_metadados(linhas, fonte, id_resposta, requisicao, ingerido_em)
    )
    return Gravacao(id_resposta, nova, len(linhas), novas)


def coletar_pais(
    pais: str,
    destino: Path | None = None,
    cliente: WorldBankClient | None = None,
) -> list[Gravacao]:
    """Coleta os indicadores de um país específico da API do Banco Mundial e grava em Delta."""
    pais_upper = pais.upper()
    if pais_upper not in PAISES:
        raise ValueError(f"País {pais} não suportado. Escolha entre: {list(PAISES.keys())}")

    destino = destino or diretorio_padrao_pais(pais_upper)

    def _executar(client: WorldBankClient) -> list[Gravacao]:
        res = []
        for nome_chave, codigo_ind in INDICADORES.items():
            logger.info("Coletando PIB de %s - %s (%s)", pais_upper, nome_chave, codigo_ind)
            resposta = client.buscar_resposta(pais_upper, codigo_ind)
            gravacao = gravar(
                destino=destino,
                indicador=codigo_ind,
                requisicao=resposta.url,
                corpo=resposta.corpo,
                pais=pais_upper,
                status_http=resposta.status_http,
                tipo_conteudo=resposta.tipo_conteudo,
            )
            logger.info(
                "%s (%s): resposta_nova=%s, lidas=%d, novas=%d",
                pais_upper,
                codigo_ind,
                gravacao.resposta_nova,
                gravacao.linhas_lidas,
                gravacao.linhas_novas,
            )
            res.append(gravacao)
        return res

    if cliente:
        return _executar(cliente)
    with WorldBankClient() as wb:
        return _executar(wb)


def coletar_todos(
    destino_base: Path = Path("data/parquet"),
    paises: Iterable[str] = PAISES_PADRAO,
) -> dict[str, list[Gravacao]]:
    """Coleta e grava em Delta os dados de todos os países parceiros."""
    resultados = {}
    with WorldBankClient() as wb:
        for p in paises:
            destino = destino_base / f"pib_{sufixo_pais(p)}"
            resultados[p] = coletar_pais(p, destino=destino, cliente=wb)
    return resultados


def importar_raw_pais(
    pais: str,
    raw_dir: Path | None = None,
    destino: Path | None = None,
) -> int:
    """Importa arquivos .json.gz antigos de raw/ para as tabelas Delta do país."""
    pais_upper = pais.upper()
    raw_dir = raw_dir or raw_dir_padrao_pais(pais_upper)
    destino = destino or diretorio_padrao_pais(pais_upper)
    sufixo = sufixo_pais(pais_upper)

    de_para = {
        f"pib_{sufixo}_crescimento.json.gz": INDICADORES["crescimento"],
        f"pib_{sufixo}_valor_usd.json.gz": INDICADORES["pib_usd"],
        f"{INDICADORES['crescimento']}.json.gz": INDICADORES["crescimento"],
        f"{INDICADORES['pib_usd']}.json.gz": INDICADORES["pib_usd"],
    }

    total_novas = 0
    for caminho in sorted(raw_dir.glob("*.json.gz")):
        codigo_ind = de_para.get(caminho.name)
        if not codigo_ind:
            logger.warning("arquivo raw ignorado: %s", caminho.name)
            continue

        with gzip.open(caminho, "rt", encoding="utf-8") as f:
            corpo = f.read()

        ingerido_em = datetime.fromtimestamp(caminho.stat().st_mtime, UTC)
        requisicao = WorldBankClient.url_publica(pais_upper, codigo_ind)

        gravacao = gravar(
            destino=destino,
            indicador=codigo_ind,
            requisicao=requisicao,
            corpo=corpo,
            pais=pais_upper,
            status_http=None,
            tipo_conteudo="application/json",
            ingerido_em=ingerido_em,
        )
        total_novas += gravacao.linhas_novas

    return total_novas


def checar_tabelas_pais(pais: str, destino: Path | None = None) -> None:
    """Verifica e relata a integridade e volumetria das tabelas Delta de um país."""
    pais_upper = pais.upper()
    destino = destino or diretorio_padrao_pais(pais_upper)
    sufixo = sufixo_pais(pais_upper)

    caminho_resp = _caminho(destino, "resposta")
    caminho_ind = _caminho(destino, "indicador")

    if not DeltaTable.is_deltatable(caminho_resp):
        raise ChecagemError(f"tabela pib_{sufixo}_resposta não existe ou não é Delta válida")
    if not DeltaTable.is_deltatable(caminho_ind):
        raise ChecagemError(f"tabela pib_{sufixo}_indicador não existe ou não é Delta válida")

    dt_resp = DeltaTable(caminho_resp)
    dt_ind = DeltaTable(caminho_ind)

    linhas_resp = dt_resp.to_pyarrow_table().num_rows
    tabela_ind = dt_ind.to_pyarrow_table()
    linhas_ind = tabela_ind.num_rows

    print(f"=== pib_{sufixo}_resposta (v{dt_resp.version()}): {linhas_resp} linhas")
    print(f"=== pib_{sufixo}_indicador (v{dt_ind.version()}): {linhas_ind} linhas")

    df = tabela_ind.to_pandas()
    for ind, grupo in df.groupby("indicador"):
        anos = grupo["ano"].nunique()
        nulos = grupo["valor"].isna().sum()
        print(f"  * Indicador {ind}: {len(grupo)} linhas, {anos} anos distintos, {nulos} nulos")
        if anos != len(grupo):
            raise ChecagemError(f"Duplicidade de anos detectada no indicador {ind} ({pais_upper})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pais",
        default="todos",
        choices=["todos", "CHN", "USA", "RUS", "chn", "usa", "rus"],
        help="País a processar (CHN, USA, RUS ou todos)",
    )
    parser.add_argument("--destino", default=None, help="Diretório de destino (opcional)")

    subparsers = parser.add_subparsers(dest="comando")
    subparsers.add_parser("coletar", help="Coleta da API do Banco Mundial e grava em Delta")
    subparsers.add_parser("importar", help="Importa arquivos raw para Delta")
    subparsers.add_parser("checar", help="Verifica a integridade das tabelas Delta")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    pais_alvo = args.pais.upper()
    paises = PAISES_PADRAO if pais_alvo == "TODOS" else (pais_alvo,)

    comando = args.comando or "coletar"
    for p in paises:
        destino = Path(args.destino) if args.destino else diretorio_padrao_pais(p)
        if comando == "coletar":
            coletar_pais(p, destino=destino)
        elif comando == "importar":
            importar_raw_pais(p, destino=destino)
        elif comando == "checar":
            checar_tabelas_pais(p, destino=destino)

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
