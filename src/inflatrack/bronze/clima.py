"""Bronze do Clima (INMET): coleta, validação e gravação em Delta, num único arquivo.

Cada sincronização do cadastro de estações vira duas coisas, gravadas no mesmo passo::

    data/parquet/clima/resposta/   clima_resposta  uma linha por resposta DIFERENTE
    data/parquet/clima/estacao/    clima_estacao   uma linha por estação meteorológica
    data/parquet/clima/medicao/    clima_medicao   uma linha por leitura diária (coleta manual)

``clima_resposta`` guarda o JSON bruto da requisição e substitui os ``.json.gz`` de
``data/raw/inmet/``.
``clima_estacao`` é a entrada do DuckDB e do dbt: tipada, com TODAS as estações meteorológicas,
SEM valores padrão inventados (campos ausentes ficam nulos).

As duas tabelas só acrescentam. Reexecutar a mesma consulta não grava nada; se o INMET atualizar
o cadastro ou a situação de uma estação, a revisão entra como linha nova e a anterior permanece.

As medições diárias exigem estações e intervalo explícitos e ficam fora da coleta diária do
catálogo (``--medicoes``).

Uso::

    uv run python -m inflatrack.bronze.clima coletar --apenas-estacoes
    uv run python -m inflatrack.bronze.clima coletar --medicoes --estacao A001 \\
        --de 2026-01-01 --ate 2026-01-31
    uv run python -m inflatrack.bronze.clima checar
    uv run python -m inflatrack.bronze.clima importar --raw-dir data/raw/inmet
    uv run python -m inflatrack.bronze.clima load --modo so_acrescenta
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
from deltalake import DeltaTable, write_deltalake

from inflatrack.clients.inmet import (
    BASE_URL,
    InmetClient,
    InmetError,
    transformar_clima_diario,
    transformar_estacoes,
)

logger = logging.getLogger("inflatrack.clima")

FONTE = "clima"
DIRETORIO_PADRAO = "data/parquet/clima"
URL_ESTACOES = f"{BASE_URL}/estacoes/T"

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

ESQUEMA_ESTACAO = pa.schema(
    [
        pa.field("estacao_id", pa.string(), nullable=False),
        pa.field("nome", pa.string(), nullable=False),
        pa.field("estado", pa.string(), nullable=False),
        pa.field("tipo", pa.string(), nullable=True),
        pa.field("latitude", pa.float64(), nullable=True),
        pa.field("longitude", pa.float64(), nullable=True),
        pa.field("altitude_m", pa.float64(), nullable=True),
        pa.field("situacao", pa.string(), nullable=True),
        pa.field("data_inicio_operacao", pa.string(), nullable=True),
        pa.field("data_fim_operacao", pa.string(), nullable=True),
        pa.field("_id_resposta", pa.string(), nullable=False),
        pa.field("_fonte", pa.string(), nullable=False),
        pa.field("_requisicao", pa.string(), nullable=False),
        pa.field("_ingerido_em", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

ESQUEMA_MEDICAO = pa.schema(
    [
        pa.field("id_medicao", pa.string(), nullable=False),
        pa.field("estacao_id", pa.string(), nullable=False),
        pa.field("data_referencia", pa.date32(), nullable=False),
        pa.field("temp_min", pa.float64()),
        pa.field("temp_max", pa.float64()),
        pa.field("temp_media", pa.float64()),
        pa.field("precipitacao_total_mm", pa.float64()),
        pa.field("umidade_relativa_media_pct", pa.float64()),
        pa.field("umidade_relativa_min_pct", pa.float64()),
        pa.field("observado", pa.bool_(), nullable=False),
        pa.field("_id_resposta", pa.string(), nullable=False),
        pa.field("_fonte", pa.string(), nullable=False),
        pa.field("_requisicao", pa.string(), nullable=False),
        pa.field("_ingerido_em", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

CHAVE_ESTACAO = (
    "estacao_id",
    "nome",
    "estado",
    "tipo",
    "situacao",
    "latitude",
    "longitude",
    "altitude_m",
)

VOLUME_REFERENCIA = 671
TOLERANCIA_ESTACOES = 0.10  # +/- 10%


class ChecagemError(ValueError):
    """A resposta não tem a forma esperada e não deve ser promovida à Bronze."""


@dataclass(frozen=True)
class Gravacao:
    """O que uma chamada de :func:`gravar` acrescentou de fato."""

    id_resposta: str
    resposta_nova: bool
    linhas_lidas: int
    linhas_novas: int


@dataclass(frozen=True)
class GravacaoMedicoes:
    """Resumo da gravação de medições diárias do INMET."""

    id_resposta: str | None
    resposta_nova: bool
    linhas_lidas: int
    linhas_novas: int


def hash_do_corpo(corpo: str) -> str:
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()


def _para_float(valor: Any) -> float | None:
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (ValueError, TypeError):
        return None


def transformar(payload: list[dict[str, Any]]) -> list[dict]:
    """Transforma a lista de estações do INMET em registros tipados.

    Não inventa valores padrão: tipo e situação vazios permanecem nulos.
    """
    if not isinstance(payload, list):
        raise ChecagemError(f"Payload deve ser lista, recebido: {type(payload)}")

    registros: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue

        estacao_id = item.get("CD_ESTACAO") or item.get("estacao_id")
        nome = item.get("DC_NOME") or item.get("nome")
        estado = item.get("SG_ESTADO") or item.get("estado")

        if not estacao_id or not nome or not estado:
            continue

        tipo = item.get("TP_ESTACAO") or item.get("tipo")
        situacao = item.get("CD_SITUACAO") or item.get("situacao")
        dt_inicio = item.get("DT_INICIO_OPERACAO") or item.get("data_inicio_operacao")
        dt_fim = item.get("DT_FIM_OPERACAO") or item.get("data_fim_operacao")

        registros.append(
            {
                "estacao_id": str(estacao_id).strip(),
                "nome": str(nome).strip(),
                "estado": str(estado).strip(),
                "tipo": str(tipo).strip() if tipo else None,
                "latitude": _para_float(item.get("VL_LATITUDE") or item.get("latitude")),
                "longitude": _para_float(item.get("VL_LONGITUDE") or item.get("longitude")),
                "altitude_m": _para_float(item.get("VL_ALTITUDE") or item.get("altitude_m")),
                "situacao": str(situacao).strip() if situacao else None,
                "data_inicio_operacao": str(dt_inicio).strip() if dt_inicio else None,
                "data_fim_operacao": str(dt_fim).strip() if dt_fim else None,
            }
        )

    if not registros:
        raise ChecagemError("Nenhuma estação pôde ser extraída do payload.")

    registros.sort(key=lambda r: r["estacao_id"])
    return registros


def checar(linhas: list[dict]) -> None:
    """Checagens de integridade e volume do catálogo de estações."""
    if not linhas:
        raise ChecagemError("Catálogo de estações meteorológicas vazio.")

    ids = [linha["estacao_id"] for linha in linhas]
    if len(ids) != len(set(ids)):
        duplicados = [eid for eid in ids if ids.count(eid) > 1]
        raise ChecagemError(f"Estações com IDs duplicados: {sorted(set(duplicados))}")

    min_esp = int(VOLUME_REFERENCIA * (1 - TOLERANCIA_ESTACOES))
    max_esp = int(VOLUME_REFERENCIA * (1 + TOLERANCIA_ESTACOES))
    if not (min_esp <= len(linhas) <= max_esp):
        raise ChecagemError(
            f"Volume de estações ({len(linhas)}) fora da faixa esperada "
            f"[{min_esp}, {max_esp}] (referência: {VOLUME_REFERENCIA})"
        )

    # Coordenadas geográficas brasileiras (aproximadamente -35 a +6 lat, -75 a -30 lon)
    for linha in linhas:
        lat = linha.get("latitude")
        lon = linha.get("longitude")
        if lat is not None and not (-36.0 <= lat <= 7.0):
            raise ChecagemError(
                f"Estação {linha['estacao_id']} ({linha['nome']}) com latitude inválida: {lat}"
            )
        if lon is not None and not (-76.0 <= lon <= -28.0):
            raise ChecagemError(
                f"Estação {linha['estacao_id']} ({linha['nome']}) com longitude inválida: {lon}"
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
    """Guarda o corpo da resposta em Delta, evitando duplicatas por hash_corpo."""
    caminho = _caminho(destino, "resposta")
    id_resposta = hash_do_corpo(corpo)
    if DeltaTable.is_deltatable(caminho):
        existentes = (
            DeltaTable(caminho)
            .to_pyarrow_dataset()
            .to_table(columns=["hash_corpo"], filter=ds.field("hash_corpo") == id_resposta)
        )
        if existentes.num_rows:
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
    return tuple(linha[coluna] for coluna in CHAVE_ESTACAO)


def _chaves_existentes(caminho: str) -> set[tuple]:
    if not DeltaTable.is_deltatable(caminho):
        return set()
    tabela = DeltaTable(caminho).to_pyarrow_dataset().to_table(columns=list(CHAVE_ESTACAO))
    colunas = [tabela.column(coluna).to_pylist() for coluna in CHAVE_ESTACAO]
    return set(zip(*colunas, strict=True))


def acrescentar_estacoes(destino: Path, linhas: list[dict]) -> int:
    """Acrescenta na tabela Delta apenas as estações novas ou atualizadas."""
    if not linhas:
        return 0
    caminho = _caminho(destino, "estacao")
    existentes = _chaves_existentes(caminho)
    novas = [linha for linha in linhas if _chave(linha) not in existentes]
    if novas:
        write_deltalake(
            caminho,
            pa.Table.from_pylist(novas, ESQUEMA_ESTACAO),
            mode="append",
        )
    return len(novas)


def _id_medicao(linha: dict) -> str:
    colunas_de_dado = (
        "estacao_id",
        "data_referencia",
        "temp_min",
        "temp_max",
        "temp_media",
        "precipitacao_total_mm",
        "umidade_relativa_media_pct",
        "umidade_relativa_min_pct",
        "observado",
    )
    conteudo = json.dumps(
        {coluna: linha.get(coluna) for coluna in colunas_de_dado},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(conteudo.encode("utf-8")).hexdigest()


def acrescentar_medicoes(destino: Path, linhas: list[dict]) -> int:
    """Acrescenta medições inéditas e mantém versões quando uma leitura é revisada."""
    if not linhas:
        return 0

    caminho = _caminho(destino, "medicao")
    linhas_com_id = [linha | {"id_medicao": _id_medicao(linha)} for linha in linhas]
    ids = {linha["id_medicao"] for linha in linhas_com_id}
    if DeltaTable.is_deltatable(caminho):
        existentes = (
            DeltaTable(caminho)
            .to_pyarrow_dataset()
            .to_table(columns=["id_medicao"], filter=ds.field("id_medicao").isin(list(ids)))
        )
        ids_existentes = set(existentes.column("id_medicao").to_pylist())
    else:
        ids_existentes = set()

    novas = [linha for linha in linhas_com_id if linha["id_medicao"] not in ids_existentes]
    if novas:
        write_deltalake(
            caminho,
            pa.Table.from_pylist(novas, ESQUEMA_MEDICAO),
            mode="append",
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
    payload: list[dict[str, Any]],
    requisicao: str = URL_ESTACOES,
    ingerido_em: datetime | None = None,
    status_http: int | None = 200,
    tipo_conteudo: str | None = "application/json; charset=utf-8",
) -> Gravacao:
    """Executa a transformação, validação e gravação nas duas tabelas Delta."""
    ingerido_em = ingerido_em or datetime.now(UTC)
    corpo = json.dumps(payload, ensure_ascii=False)
    linhas = transformar(payload)
    checar(linhas)

    id_resposta, nova = gravar_resposta(
        destino,
        requisicao=requisicao,
        corpo=corpo,
        ingerido_em=ingerido_em,
        status_http=status_http,
        tipo_conteudo=tipo_conteudo,
    )
    novas = acrescentar_estacoes(
        destino, _com_metadados(linhas, id_resposta, requisicao, ingerido_em)
    )
    return Gravacao(id_resposta, nova, len(linhas), novas)


def gravar_medicoes(
    destino: Path,
    payload: list[dict[str, Any]],
    requisicao: str,
    ingerido_em: datetime | None = None,
    status_http: int | None = 200,
    tipo_conteudo: str | None = "application/json; charset=utf-8",
) -> GravacaoMedicoes:
    """Valida e grava uma resposta diária do INMET nas tabelas Delta.

    Respostas sem observações não são armazenadas. Leituras revisadas geram uma nova
    linha, enquanto a reexecução de uma leitura idêntica é idempotente.
    """
    linhas_df = transformar_clima_diario(payload)
    linhas_df = linhas_df.astype(object).where(linhas_df.notna(), None)
    linhas = linhas_df.to_dict(orient="records")
    if not linhas:
        return GravacaoMedicoes(None, False, 0, 0)

    ingerido_em = ingerido_em or datetime.now(UTC)
    corpo = json.dumps(payload, ensure_ascii=False)
    id_resposta, nova = gravar_resposta(
        destino,
        requisicao=requisicao,
        corpo=corpo,
        ingerido_em=ingerido_em,
        status_http=status_http,
        tipo_conteudo=tipo_conteudo,
    )
    linhas_com_metadados = _com_metadados(linhas, id_resposta, requisicao, ingerido_em)
    novas = acrescentar_medicoes(destino, linhas_com_metadados)
    return GravacaoMedicoes(id_resposta, nova, len(linhas), novas)


def processar_estacoes(
    cliente: InmetClient, destino: Path = Path(DIRETORIO_PADRAO)
) -> pd.DataFrame:
    """Coleta o catálogo de estações ativas e grava na Bronze Delta."""
    logger.info("Consultando catálogo de estações ativas do INMET...")
    payload = cliente.listar_estacoes(tipo="T")
    grav = gravar(destino, payload)
    logger.info(
        "Bronze Delta: resposta %s, %d de %d estações novas em %s",
        "nova" if grav.resposta_nova else "já guardada",
        grav.linhas_novas,
        grav.linhas_lidas,
        destino,
    )
    return transformar_estacoes(payload)


def processar_medicoes(
    cliente: InmetClient,
    estacoes: list[str],
    data_inicio: str,
    data_fim: str,
    destino: Path = Path(DIRETORIO_PADRAO),
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
        grav = gravar_medicoes(
            destino,
            payload,
            requisicao=f"{BASE_URL}/estacao/diaria/{endpoint}",
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


def importar_raw(
    raw_dir: Path,
    destino: Path,
) -> tuple[int, int, list[str]]:
    """Importa estacoes.json.gz de data/raw/inmet/ para as duas tabelas Delta."""
    respostas = estacoes_novas = 0
    falhas: list[str] = []

    for caminho in sorted(raw_dir.glob("estacoes*.json.gz")):
        try:
            with gzip.open(caminho, "rt", encoding="utf-8") as f:
                payload = json.load(f)
            ingerido_em = datetime.fromtimestamp(caminho.stat().st_mtime, UTC)
            grav = gravar(
                destino,
                payload=payload,
                requisicao=URL_ESTACOES,
                ingerido_em=ingerido_em,
                status_http=None,
                tipo_conteudo=None,
            )
            respostas += int(grav.resposta_nova)
            estacoes_novas += grav.linhas_novas
        except Exception as erro:
            falhas.append(f"{caminho.name}: {erro}")

    return respostas, estacoes_novas, falhas


def checar_tabela(destino: Path) -> dict:
    """Inspeciona a tabela clima_estacao gravada em Delta."""
    caminho = _caminho(destino, "estacao")
    if not DeltaTable.is_deltatable(caminho):
        raise ChecagemError(f"Tabela Delta não encontrada em {caminho}")

    dt = DeltaTable(caminho)
    tbl = dt.to_pyarrow_table()
    linhas = tbl.to_pylist()
    checar(linhas)

    estados = {linha["estado"] for linha in linhas}
    tipos = {linha["tipo"] for linha in linhas}
    return {
        "linhas": len(linhas),
        "estados": len(estados),
        "tipos": sorted(str(t) for t in tipos if t),
        "versoes": dt.version(),
    }


def carregar_duckdb(
    destino: Path,
    db_caminho: Path | str = "data/duckdb/inflatrack.duckdb",
    modo: str = "substitui",
) -> int:
    """Carrega a tabela Delta clima_estacao no DuckDB nos dois modos do contrato."""
    import duckdb

    from inflatrack.loaders import load_clima

    db = Path(db_caminho)
    db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db)) as conexao:
        return load_clima.carregar_bronze_estacoes(conexao, destino, modo=modo)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="comando", required=True)

    p_coletar = subparsers.add_parser("coletar", help="Baixa da API do INMET e grava em Delta")
    p_coletar.add_argument("--destino", default=DIRETORIO_PADRAO)
    p_coletar.add_argument(
        "--apenas-estacoes",
        action="store_true",
        help="Só o cadastro de estações (é o que a coleta faz sem --medicoes)",
    )
    p_coletar.add_argument(
        "--medicoes", action="store_true", help="Também busca medições diárias das estações"
    )
    p_coletar.add_argument("--estacao", action="append", default=[], help="ID INMET; pode repetir")
    p_coletar.add_argument("--de", dest="data_inicio", help="Data inicial AAAA-MM-DD")
    p_coletar.add_argument("--ate", dest="data_fim", help="Data final AAAA-MM-DD")

    p_checar = subparsers.add_parser("checar", help="Verifica a tabela Delta gravada")
    p_checar.add_argument("--destino", default=DIRETORIO_PADRAO)

    p_importar = subparsers.add_parser("importar", help="Importa do raw antigo")
    p_importar.add_argument("--raw-dir", default="data/raw/inmet")
    p_importar.add_argument("--destino", default=DIRETORIO_PADRAO)

    p_load = subparsers.add_parser("load", help="Carrega a tabela Delta no DuckDB")
    p_load.add_argument("--destino", default=DIRETORIO_PADRAO)
    p_load.add_argument("--db", default="data/duckdb/inflatrack.duckdb")
    p_load.add_argument(
        "--modo",
        choices=["substitui", "so_acrescenta"],
        default="substitui",
        help="Modo de carga: 'substitui' ou 'so_acrescenta'",
    )

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    destino = Path(args.destino)
    if args.comando == "coletar":
        if args.medicoes and not (args.data_inicio and args.data_fim):
            parser.error("--medicoes exige --de e --ate")
        cliente = InmetClient()
        try:
            processar_estacoes(cliente, destino)
            if args.medicoes:
                respostas, leituras = processar_medicoes(
                    cliente, args.estacao, args.data_inicio, args.data_fim, destino
                )
                logger.info(
                    "Bronze diária: %d respostas novas, %d medições novas", respostas, leituras
                )
            return 0
        except (InmetError, ChecagemError) as erro:
            logger.error("Erro na API do INMET: %s", erro)
            return 1
        except Exception:
            logger.exception("Falha inesperada na coleta do clima")
            return 1
    if args.comando == "checar":
        try:
            info = checar_tabela(destino)
            print(
                f"clima_estacao linhas={info['linhas']} estados={info['estados']} "
                f"tipos={info['tipos']} versoes={info['versoes']} status=OK"
            )
            return 0
        except ChecagemError as erro:
            logger.error("Checagem falhou: %s", erro)
            return 1
    if args.comando == "importar":
        respostas, novas, falhas = importar_raw(Path(args.raw_dir), destino)
        logger.info(
            "Importação: %d respostas novas, %d estações novas, %d falhas",
            respostas,
            novas,
            len(falhas),
        )
        for f in falhas:
            logger.warning("Falha: %s", f)
        return 0 if not falhas else 1
    if args.comando == "load":
        total = carregar_duckdb(destino, db_caminho=args.db, modo=args.modo)
        logger.info(
            "Carga no DuckDB concluída (%s): %d estações em bronze.clima_estacao",
            args.modo,
            total,
        )
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
