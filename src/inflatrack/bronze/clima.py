"""Bronze do Clima (INMET): coleta, validação e gravação em Delta, num único arquivo.

Duas coletas gravam no mesmo diretório Delta::

    data/parquet/clima/resposta/   clima_resposta  uma linha por resposta DIFERENTE
    data/parquet/clima/estacao/    clima_estacao   uma linha por versão de estação do catálogo
    data/parquet/clima/medicao/    clima_medicao   uma linha por versão de leitura diária

**Catálogo** (``coletar``): o JSON de ``apitempo.inmet.gov.br/estacoes/T``. Sem valores padrão
inventados: campos ausentes ficam nulos.

**Medições** (``coletar --medicoes``): os pacotes anuais do BDMEP
(``portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip``), porque a rota diária da API foi
desativada (``docs/evidencias/e2/clima.md``). De cada pacote só entram as estações do de-para
``dbt/seeds/seed_de_para_estacao_localidade.csv``, o mesmo que a Silver usa. O CSV original de
cada estação vai inteiro para ``clima_resposta`` (Raw) e as leituras horárias viram um resumo por
dia UTC em ``clima_medicao``. Uma métrica do dia só sai com pelo menos ``HORAS_MINIMAS`` horas
válidas: com menos, a chuva somada subestimaria o dia e a máxima podia não ter sido medida.

Para não baixar ~1 GB todo dia, cada pacote processado deixa em ``clima_resposta`` um manifesto
com a versão publicada (``Last-Modified`` e tamanho) e a lista de estações. A próxima coleta faz
um HEAD por ano e só baixa o pacote se a versão publicada, a lista de estações ou a regra de
leitura (``VERSAO_LEITURA``) mudou. Assim a primeira
execução traz a série desde ``ANO_INICIAL`` e as seguintes só o que o INMET republicou.

Todas as tabelas só acrescentam. Reexecutar não grava nada; uma revisão do INMET (no cadastro ou
numa leitura) entra como linha nova e a anterior permanece.

Uso::

    uv run python -m inflatrack.bronze.clima coletar
    uv run python -m inflatrack.bronze.clima coletar --medicoes
    uv run python -m inflatrack.bronze.clima coletar --medicoes --estacao A001 \\
        --de-ano 2024 --ate-ano 2025
    uv run python -m inflatrack.bronze.clima checar
    uv run python -m inflatrack.bronze.clima importar --raw-dir data/raw/inmet
    uv run python -m inflatrack.bronze.clima load --modo so_acrescenta
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import logging
import re
import sys
import tempfile
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
from deltalake import DeltaTable, write_deltalake

from inflatrack.clients.inmet import (
    BASE_URL,
    InmetClient,
    InmetError,
    VersaoZip,
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
        pa.field("horas_com_registro", pa.int16()),
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

FUSO = ZoneInfo("America/Sao_Paulo")
# Primeiro ano coletado: o mesmo início da série de poder de compra (salário mínimo e IPCA).
ANO_INICIAL = 2006
# 18 de 24 leituras horárias (75%): abaixo disso a métrica do dia fica nula.
HORAS_MINIMAS = 18
MAPEAMENTO_ESTACOES = (
    Path(__file__).resolve().parents[3] / "dbt" / "seeds" / "seed_de_para_estacao_localidade.csv"
)
TIPO_CSV_BDMEP = "text/csv; charset=iso-8859-1"
# Suba quando a leitura do CSV mudar: o manifesto muda e os pacotes já gravados são relidos uma
# vez (só leituras com valor diferente viram linha nova).
VERSAO_LEITURA = 2
TIPO_MANIFESTO = "application/json; charset=utf-8"


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
    """Resumo da gravação de um lote de CSVs do BDMEP."""

    respostas_novas: int
    linhas_lidas: int
    linhas_novas: int
    falhas: tuple[str, ...] = ()


@dataclass
class ResumoMedicoes:
    """O que uma coleta de medições fez, ano a ano."""

    anos_processados: list[int] = field(default_factory=list)
    anos_inalterados: list[int] = field(default_factory=list)
    anos_nao_publicados: list[int] = field(default_factory=list)
    respostas_novas: int = 0
    medicoes_novas: int = 0
    falhas: list[str] = field(default_factory=list)


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
        "horas_com_registro",
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

    # Dois CSVs do mesmo lote podem trazer a mesma leitura: um id só uma vez.
    unicas = {linha["id_medicao"]: linha for linha in linhas_com_id}
    novas = [linha for id_, linha in unicas.items() if id_ not in ids_existentes]
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


def estacoes_mapeadas(caminho: Path | None = None) -> list[str]:
    """As estações do de-para estação -> localidade do IPCA, o mesmo seed que a Silver usa."""
    caminho = caminho or MAPEAMENTO_ESTACOES
    with caminho.open(encoding="utf-8", newline="") as arquivo:
        estacoes = {linha["estacao_id"].strip() for linha in csv.DictReader(arquivo)}
    if not estacoes or "" in estacoes:
        raise ChecagemError(f"Mapeamento de estações vazio ou inválido: {caminho}")
    return sorted(estacoes)


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(sem_acento.upper().split())


# Coluna -> início do nome normalizado no CSV. O cabeçalho mudou de grafia em 2019
# ("DATA (YYYY-MM-DD);HORA (UTC)" virou "Data;Hora UTC"), mas as medidas mantêm o prefixo.
COLUNAS_BDMEP = {
    "precipitacao": "PRECIPITACAO TOTAL, HORARIO",
    "temperatura": "TEMPERATURA DO AR - BULBO SECO, HORARIA",
    "temp_max": "TEMPERATURA MAXIMA NA HORA ANT.",
    "temp_min": "TEMPERATURA MINIMA NA HORA ANT.",
    "umidade": "UMIDADE RELATIVA DO AR, HORARIA",
    "umidade_min": "UMIDADE REL. MIN. NA HORA ANT.",
}

# Faixas físicas plausíveis. Fora delas é defeito de sensor e vira nulo (não zero).
FAIXAS_BDMEP = {
    "precipitacao": (0.0, 200.0),
    "temperatura": (-15.0, 50.0),
    "temp_max": (-15.0, 50.0),
    "temp_min": (-15.0, 50.0),
    "umidade": (0.0, 100.0),
    "umidade_min": (0.0, 100.0),
}

_ARQUIVO_BDMEP = re.compile(r"^INMET_[A-Z]+_[A-Z]{2}_([A-Z]\d{3})_", re.IGNORECASE)


def estacao_do_arquivo(nome: str) -> str | None:
    """``2025/INMET_CO_DF_A001_BRASILIA_01-01-2025_A_31-12-2025.CSV`` -> ``A001``."""
    achado = _ARQUIVO_BDMEP.match(Path(nome).name)
    return achado.group(1).upper() if achado else None


def _valor_bdmep(bruto: str, faixa: tuple[float, float]) -> float | None:
    """Vírgula decimal; vazio e -9999 são ausência. Zero é medida e fica zero."""
    bruto = bruto.strip()
    if not bruto:
        return None
    try:
        numero = float(bruto.replace(",", "."))
    except ValueError:
        return None
    if numero <= -9999 or not faixa[0] <= numero <= faixa[1]:
        return None
    return numero


def _data_bdmep(bruto: str) -> date:
    return date.fromisoformat(bruto.strip().replace("/", "-"))


@dataclass(frozen=True)
class LeituraBdmep:
    estacao_id: str
    linhas: list[dict]


def _media(valores: list[float]) -> float:
    return sum(valores) / len(valores)


def _resumo_do_dia(valores: list[float], funcao) -> float | None:
    return round(funcao(valores), 3) if len(valores) >= HORAS_MINIMAS else None


def transformar_csv_bdmep(texto: str) -> LeituraBdmep:
    """Lê o CSV horário de uma estação e devolve uma linha por dia UTC com dado válido."""
    linhas_arquivo = texto.splitlines()
    estacao_id = None
    inicio_dados = None
    for indice, linha in enumerate(linhas_arquivo[:20]):
        rotulo, _, valor = linha.partition(";")
        rotulo = _normalizar(rotulo)
        if rotulo.startswith("CODIGO (WMO)"):
            estacao_id = valor.strip(" ;").upper()
        elif rotulo.startswith("DATA") and linha.count(";") >= len(COLUNAS_BDMEP):
            # O cabeçalho dos dados é a linha "Data;Hora..." com todas as colunas. Não basta
            # excluir "DATA DE FUNDAÇÃO": em 2019 o INMET gravou os acentos como "?".
            inicio_dados = indice
            break
    if not estacao_id or inicio_dados is None:
        raise ChecagemError("CSV do BDMEP sem código da estação ou sem cabeçalho de dados")

    cabecalho = [_normalizar(coluna) for coluna in linhas_arquivo[inicio_dados].split(";")]
    posicoes = {}
    for coluna, prefixo in COLUNAS_BDMEP.items():
        achadas = [i for i, nome in enumerate(cabecalho) if nome.startswith(prefixo)]
        if not achadas:
            raise ChecagemError(f"CSV do BDMEP de {estacao_id} sem a coluna {prefixo!r}")
        posicoes[coluna] = achadas[0]

    # Uma leitura por (dia, hora): se a hora vier repetida, vale a última linha.
    leituras: dict[tuple[date, str], dict[str, float | None]] = {}
    for linha in linhas_arquivo[inicio_dados + 1 :]:
        campos = linha.split(";")
        if len(campos) <= max(posicoes.values()):
            continue
        try:
            dia = _data_bdmep(campos[0])
        except ValueError:
            continue
        leituras[(dia, campos[1].strip())] = {
            coluna: _valor_bdmep(campos[posicao], FAIXAS_BDMEP[coluna])
            for coluna, posicao in posicoes.items()
        }

    por_dia: dict[date, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    horas: dict[date, int] = defaultdict(int)
    for (dia, _hora), valores in leituras.items():
        if all(valor is None for valor in valores.values()):
            continue
        horas[dia] += 1
        for coluna, valor in valores.items():
            if valor is not None:
                por_dia[dia][coluna].append(valor)

    diarias = []
    for dia in sorted(horas):
        medidas = por_dia[dia]
        diarias.append(
            {
                "estacao_id": estacao_id,
                "data_referencia": dia,
                "temp_min": _resumo_do_dia(medidas["temp_min"], min),
                "temp_max": _resumo_do_dia(medidas["temp_max"], max),
                "temp_media": _resumo_do_dia(medidas["temperatura"], _media),
                "precipitacao_total_mm": _resumo_do_dia(medidas["precipitacao"], sum),
                "umidade_relativa_media_pct": _resumo_do_dia(medidas["umidade"], _media),
                "umidade_relativa_min_pct": _resumo_do_dia(medidas["umidade_min"], min),
                "horas_com_registro": horas[dia],
                "observado": True,
            }
        )
    return LeituraBdmep(estacao_id, diarias)


def _acrescentar_respostas(destino: Path, respostas: list[dict]) -> int:
    """Grava as respostas cujo hash ainda não está em ``clima_resposta``; devolve quantas."""
    caminho = _caminho(destino, "resposta")
    unicas = {resposta["id_resposta"]: resposta for resposta in respostas}
    if DeltaTable.is_deltatable(caminho):
        existentes = (
            DeltaTable(caminho)
            .to_pyarrow_dataset()
            .to_table(columns=["hash_corpo"], filter=ds.field("hash_corpo").isin(list(unicas)))
        )
        for hash_corpo in existentes.column("hash_corpo").to_pylist():
            unicas.pop(hash_corpo, None)
    if unicas:
        write_deltalake(
            caminho, pa.Table.from_pylist(list(unicas.values()), ESQUEMA_RESPOSTA), mode="append"
        )
    return len(unicas)


def _resposta_existe(destino: Path, id_resposta: str) -> bool:
    caminho = _caminho(destino, "resposta")
    if not DeltaTable.is_deltatable(caminho):
        return False
    return bool(
        DeltaTable(caminho)
        .to_pyarrow_dataset()
        .count_rows(filter=ds.field("hash_corpo") == id_resposta)
    )


def _linha_resposta(corpo: str, requisicao: str, ingerido_em: datetime, tipo_conteudo: str) -> dict:
    id_resposta = hash_do_corpo(corpo)
    return {
        "id_resposta": id_resposta,
        "_fonte": FONTE,
        "_requisicao": requisicao,
        "_ingerido_em": ingerido_em,
        "status_http": 200,
        "tipo_conteudo": tipo_conteudo,
        "corpo": corpo,
        "hash_corpo": id_resposta,
        "tamanho_bytes": len(corpo.encode("utf-8")),
    }


def gravar_csvs_bdmep(
    destino: Path,
    arquivos: list[tuple[str, str]],
    ingerido_em: datetime | None = None,
) -> GravacaoMedicoes:
    """Grava um lote de CSVs do BDMEP (``(requisicao, texto)``) com um commit por tabela.

    O CSV inteiro vai para ``clima_resposta``; as leituras diárias, para ``clima_medicao``.
    CSV sem nenhum dia válido não é guardado (resposta vazia não entra no Raw).
    """
    ingerido_em = ingerido_em or datetime.now(UTC)
    respostas, medicoes, falhas = [], [], []
    for requisicao, texto in arquivos:
        try:
            leitura = transformar_csv_bdmep(texto)
            esperada = estacao_do_arquivo(requisicao.rsplit("#", 1)[-1])
            if esperada is not None and esperada != leitura.estacao_id:
                raise ChecagemError(
                    f"cabeçalho diz {leitura.estacao_id}, o nome do arquivo diz {esperada}"
                )
        except ChecagemError as erro:
            logger.error("CSV do BDMEP recusado (%s): %s", requisicao, erro)
            falhas.append(f"{requisicao}: {erro}")
            continue
        if not leitura.linhas:
            logger.info("Sem leituras válidas em %s", requisicao)
            continue
        resposta = _linha_resposta(texto, requisicao, ingerido_em, TIPO_CSV_BDMEP)
        respostas.append(resposta)
        medicoes.extend(
            _com_metadados(leitura.linhas, resposta["id_resposta"], requisicao, ingerido_em)
        )
    respostas_novas = _acrescentar_respostas(destino, respostas) if respostas else 0
    medicoes_novas = acrescentar_medicoes(destino, medicoes)
    return GravacaoMedicoes(respostas_novas, len(medicoes), medicoes_novas, tuple(falhas))


def manifesto_do_pacote(versao: VersaoZip, estacoes: list[str]) -> str | None:
    """Identidade de um pacote processado. Sem data e tamanho não há como saber se mudou."""
    if versao.ultima_modificacao is None or versao.tamanho_bytes is None:
        logger.warning(
            "BDMEP %d sem Last-Modified ou Content-Length: o pacote será baixado a cada coleta",
            versao.ano,
        )
        return None
    return json.dumps(
        {
            "versao_leitura": VERSAO_LEITURA,
            "url": versao.url,
            "ultima_modificacao": versao.ultima_modificacao,
            "tamanho_bytes": versao.tamanho_bytes,
            "estacoes": sorted(estacoes),
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def processar_zip_bdmep(
    caminho_zip: Path,
    url: str,
    estacoes: list[str],
    destino: Path,
    ingerido_em: datetime | None = None,
) -> tuple[GravacaoMedicoes, set[str]]:
    """Extrai do pacote anual os CSVs das estações pedidas e grava em Delta."""
    pedidas = set(estacoes)
    arquivos, encontradas = [], set()
    with zipfile.ZipFile(caminho_zip) as pacote:
        # O mesmo nome pode aparecer duas vezes no índice do zip (visto em 2025.zip).
        nomes = sorted({info.filename for info in pacote.infolist() if not info.is_dir()})
        for nome in nomes:
            estacao_id = estacao_do_arquivo(nome)
            if estacao_id not in pedidas:
                continue
            encontradas.add(estacao_id)
            arquivos.append((f"{url}#{nome}", pacote.read(nome).decode("latin-1")))
    return gravar_csvs_bdmep(destino, arquivos, ingerido_em), encontradas


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


def anos_padrao(hoje: date | None = None) -> list[int]:
    hoje = hoje or datetime.now(FUSO).date()
    return list(range(ANO_INICIAL, hoje.year + 1))


def processar_medicoes(
    cliente: InmetClient,
    estacoes: list[str],
    anos: list[int],
    destino: Path = Path(DIRETORIO_PADRAO),
    ano_corrente: int | None = None,
) -> ResumoMedicoes:
    """Baixa e grava os pacotes anuais que mudaram desde a última coleta.

    Uma falha num ano não interrompe os outros: ela fica em ``falhas`` e o manifesto daquele
    ano não é gravado, então a próxima coleta tenta de novo. São falhas: o pacote de um ano já
    encerrado não existir, o pacote não ter nenhuma das estações pedidas e um CSV recusado.
    Estação que falta só em parte dos anos (começou depois, parou antes) é aviso, não falha.
    """
    if not estacoes:
        raise ValueError("Informe ao menos uma estação para coletar medições.")
    ano_corrente = ano_corrente or datetime.now(FUSO).year
    resumo = ResumoMedicoes()
    for ano in anos:
        try:
            versao = cliente.versao_zip_anual(ano)
            if versao is None:
                if ano < ano_corrente:
                    raise InmetError(f"pacote de {ano} não encontrado no portal (404)")
                logger.info("BDMEP %d ainda não publicado", ano)
                resumo.anos_nao_publicados.append(ano)
                continue
            manifesto = manifesto_do_pacote(versao, estacoes)
            if manifesto is not None and _resposta_existe(destino, hash_do_corpo(manifesto)):
                logger.info("BDMEP %d sem mudança desde a última coleta", ano)
                resumo.anos_inalterados.append(ano)
                continue

            ingerido_em = datetime.now(UTC)
            with tempfile.TemporaryDirectory(prefix="inmet_") as temporario:
                caminho = cliente.baixar_zip_anual(ano, Path(temporario) / f"{ano}.zip")
                grav, encontradas = processar_zip_bdmep(
                    caminho, versao.url, estacoes, destino, ingerido_em
                )
            if not encontradas:
                raise ChecagemError(f"pacote de {ano} sem nenhuma das estações pedidas")
            ausentes = sorted(set(estacoes) - encontradas)
            if ausentes:
                logger.warning("BDMEP %d sem as estações %s", ano, ", ".join(ausentes))
            resumo.respostas_novas += grav.respostas_novas
            resumo.medicoes_novas += grav.linhas_novas
            if grav.falhas:
                resumo.falhas.extend(f"{ano}: {falha}" for falha in grav.falhas)
                continue
            if manifesto is not None:
                _acrescentar_respostas(
                    destino,
                    [_linha_resposta(manifesto, versao.url, ingerido_em, TIPO_MANIFESTO)],
                )
        except Exception as erro:  # rede, zip corrompido ou CSV fora do formato
            logger.exception("BDMEP %d falhou", ano)
            resumo.falhas.append(f"{ano}: {erro}")
            continue

        resumo.anos_processados.append(ano)
        logger.info(
            "BDMEP %d: %d estações, %d CSVs novos, %d de %d leituras diárias novas",
            ano,
            len(encontradas),
            grav.respostas_novas,
            grav.linhas_novas,
            grav.linhas_lidas,
        )
    return resumo


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

    p_coletar = subparsers.add_parser("coletar", help="Baixa do INMET e grava em Delta")
    p_coletar.add_argument("--destino", default=DIRETORIO_PADRAO)
    modos = p_coletar.add_mutually_exclusive_group()
    modos.add_argument(
        "--apenas-estacoes",
        action="store_true",
        help="Só o catálogo de estações (é o que a coleta faz sem --medicoes)",
    )
    modos.add_argument(
        "--medicoes",
        action="store_true",
        help=(
            f"Só as medições do BDMEP: estações do de-para, de {ANO_INICIAL} até o ano corrente, "
            "baixando apenas os pacotes que mudaram"
        ),
    )
    p_coletar.add_argument(
        "--estacao", action="append", default=[], help="ID INMET no lugar do de-para; pode repetir"
    )
    p_coletar.add_argument("--de-ano", type=int, help=f"Primeiro ano (padrão {ANO_INICIAL})")
    p_coletar.add_argument("--ate-ano", type=int, help="Último ano (padrão: o corrente)")

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
        if not args.medicoes and (args.estacao or args.de_ano or args.ate_ano):
            parser.error("--estacao, --de-ano e --ate-ano exigem --medicoes")
        cliente = InmetClient()
        if not args.medicoes:
            try:
                processar_estacoes(cliente, destino)
                return 0
            except (InmetError, ChecagemError) as erro:
                logger.error("Erro na API do INMET: %s", erro)
                return 1
            except Exception:
                logger.exception("Falha inesperada na coleta do catálogo de estações")
                return 1

        anos = anos_padrao()
        de_ano = args.de_ano or anos[0]
        ate_ano = args.ate_ano or anos[-1]
        if de_ano > ate_ano:
            parser.error("--de-ano deve ser menor ou igual a --ate-ano")
        try:
            estacoes = args.estacao or estacoes_mapeadas()
        except (OSError, ChecagemError) as erro:
            logger.error("%s", erro)
            return 1
        resumo = processar_medicoes(cliente, estacoes, list(range(de_ano, ate_ano + 1)), destino)
        logger.info(
            "BDMEP: %d anos processados, %d sem mudança, %d não publicados; "
            "%d CSVs novos, %d leituras diárias novas, %d falhas",
            len(resumo.anos_processados),
            len(resumo.anos_inalterados),
            len(resumo.anos_nao_publicados),
            resumo.respostas_novas,
            resumo.medicoes_novas,
            len(resumo.falhas),
        )
        return 1 if resumo.falhas else 0
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
