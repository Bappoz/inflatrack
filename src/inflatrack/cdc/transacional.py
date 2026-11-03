"""CDC do banco do lojista: lê as mudanças de `public` e acrescenta na Bronze, sem CNPJ.

O Postgres publica ``lojista``, ``produto``, ``reajuste``, ``reajuste_custo`` e ``venda_mensal``
(publicação ``inflatrack_cdc``, migration 0004). Este módulo lê o slot lógico pela função SQL
``pg_logical_slot_peek_binary_changes``, com o plugin nativo ``pgoutput``, e grava uma linha por
mudança em ``data/parquet/transacional/mudanca/`` (decisão e alternativas no ADR de ingestão).

A ordem é o que garante que nada se perde nem duplica::

    espiar o slot (não consome) -> gravar no Delta -> só então avançar o slot

Cair entre a gravação e o avanço faz o próximo ciclo ler as mesmas mudanças de novo, e a chave
(``lsn``, tabela, operação e registro) as ignora. O WAL guarda o histórico que o slot ainda não
consumiu, então nem CDC parado nem Postgres reiniciado perdem evento, até o limite de
``max_slot_wal_keep_size``; passou disso, o slot é invalidado e este módulo falha com erro claro.

A primeira execução cria o slot e grava uma foto das tabelas (``operacao = 'r'``), porque o slot
só enxerga o que acontece depois dele. Uma mudança que caia entre o slot e a foto aparece nos
dois lugares, e a Silver chega ao mesmo estado final ao aplicar os eventos em ordem.

LGPD: o CNPJ nunca chega à Bronze. Em ``lojista`` só passam as colunas de
:data:`COLUNAS_LOJISTA`: uma coluna nova não vaza por esquecimento, e ``nome_fantasia`` também
fica de fora, porque nome de MEI costuma ser nome de pessoa. O CNPJ vira
``hash_estabelecimento``, um HMAC-SHA256 com chave: é **pseudonimização**, não anonimização, pois
quem tem a chave consegue confirmar um CNPJ. Sem a chave, um SHA-256 puro seria revertido por
força bruta. O WAL do Postgres ainda contém o CNPJ, como a própria tabela de origem.

Uso::

    uv run python -m inflatrack.cdc.transacional
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import struct
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pyarrow as pa
from dotenv import load_dotenv
from psycopg import sql

from inflatrack.common import bronze
from inflatrack.common.db import dsn_do_ambiente

logger = logging.getLogger("inflatrack.cdc")

FONTE = "transacional"
DIRETORIO_PADRAO = "data/parquet/transacional"
TABELA_DELTA = "mudanca"
SLOT_PADRAO = "inflatrack_cdc"
PUBLICACAO = "inflatrack_cdc"
VARIAVEL_CHAVE = "CDC_CHAVE_PSEUDONIMO"

TABELAS = ("lojista", "produto", "reajuste", "reajuste_custo", "venda_mensal")

# Lista do que PODE sair, e não do que não pode: coluna nova fica de fora até alguém decidir.
COLUNAS_LOJISTA = frozenset({"id", "codigo_localidade", "codigo_grupo_ipca", "criado_em"})

# Limite de mudanças por leitura do slot. O Postgres só para em fim de transação.
MUDANCAS_POR_LOTE = 10_000

ESQUEMA_MUDANCA = bronze.esquema_extraido(
    [
        pa.field("lsn", pa.int64(), nullable=False),
        pa.field("lsn_commit", pa.int64(), nullable=False),
        pa.field("id_transacao", pa.int64(), nullable=False),
        pa.field("tabela", pa.string(), nullable=False),
        pa.field("operacao", pa.string(), nullable=False),
        pa.field("id_registro", pa.int64()),
        pa.field("antes", pa.string()),
        pa.field("depois", pa.string()),
        pa.field("commit_em", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

# Uma mudança é identificada pela posição no WAL. A mesma leitura repetida gera a mesma chave.
CHAVE_MUDANCA = ("lsn", "tabela", "operacao", "id_registro")

_EPOCA_POSTGRES = datetime(2000, 1, 1, tzinfo=UTC)
_NAO_ALTERADO = object()  # coluna TOAST que o pgoutput não reenviou por não ter mudado


class CdcError(RuntimeError):
    """O CDC não tem como continuar sem intervenção (configuração ou slot inválido)."""


@dataclass(frozen=True)
class Captura:
    """O que um ciclo de captura leu e o que entrou de fato no Delta."""

    lidas: int
    novas: int
    foto: bool


# --- Protocolo pgoutput ------------------------------------------------------------


class _Leitor:
    """Lê os campos big-endian de uma mensagem do protocolo de replicação lógica."""

    def __init__(self, dados: bytes) -> None:
        self.dados, self.posicao = dados, 0

    def _ler(self, formato: str) -> int:
        valor = struct.unpack_from(formato, self.dados, self.posicao)[0]
        self.posicao += struct.calcsize(formato)
        return valor

    def byte(self) -> str:
        return chr(self._ler(">B"))

    def int16(self) -> int:
        return self._ler(">h")

    def int32(self) -> int:
        return self._ler(">i")

    def uint32(self) -> int:
        return self._ler(">I")

    def int64(self) -> int:
        return self._ler(">q")

    def texto(self) -> str:
        fim = self.dados.index(b"\0", self.posicao)
        valor = self.dados[self.posicao : fim].decode("utf-8")
        self.posicao = fim + 1
        return valor

    def bytes_de(self, tamanho: int) -> bytes:
        valor = self.dados[self.posicao : self.posicao + tamanho]
        self.posicao += tamanho
        return valor

    def tupla(self, colunas: list[str]) -> dict[str, object]:
        quantidade = self.int16()
        valores: dict[str, object] = {}
        for coluna in colunas[:quantidade]:
            tipo = self.byte()
            if tipo == "n":
                valores[coluna] = None
            elif tipo == "u":
                valores[coluna] = _NAO_ALTERADO
            elif tipo == "t":
                valores[coluna] = self.bytes_de(self.int32()).decode("utf-8")
            else:
                raise CdcError(f"tipo de coluna desconhecido no pgoutput: {tipo!r}")
        return valores


def _preencher_nao_alterados(
    depois: dict[str, object], antes: dict[str, object] | None
) -> dict[str, object]:
    return {
        coluna: (antes or {}).get(coluna) if valor is _NAO_ALTERADO else valor
        for coluna, valor in depois.items()
    }


def decodificar(mensagens: Iterable[tuple[int, int, bytes]]) -> tuple[list[dict], int | None]:
    """Traduz as mensagens do slot em mudanças e devolve também a posição para avançar o slot.

    Cada mensagem é ``(lsn, xid, dados)``. Devolve ``(mudancas, fim_da_ultima_transacao)``. O
    avanço usa o ``end_lsn`` do commit: avançar só até o ``lsn`` da linha repetiria a transação.
    """
    relacoes: dict[int, tuple[str, list[str]]] = {}
    mudancas: list[dict] = []
    fim: int | None = None
    lsn_commit = xid_atual = 0
    commit_em = _EPOCA_POSTGRES

    def registrar(lsn: int, relid: int, operacao: str, antes, depois) -> None:
        (tabela, _) = relacoes[relid]
        mudancas.append(
            {
                "lsn": lsn,
                "lsn_commit": lsn_commit,
                "id_transacao": xid_atual,
                "tabela": tabela,
                "operacao": operacao,
                "antes": antes,
                "depois": depois,
                "commit_em": commit_em,
            }
        )

    for lsn, _, dados in mensagens:
        leitor = _Leitor(bytes(dados))
        tipo = leitor.byte()
        if tipo == "B":
            lsn_commit = leitor.int64()
            commit_em = _EPOCA_POSTGRES + timedelta(microseconds=leitor.int64())
            xid_atual = leitor.uint32()
        elif tipo == "C":
            leitor.byte()  # flags, sempre 0
            leitor.int64()  # lsn do commit, já lido no B
            fim = leitor.int64()
        elif tipo == "R":
            relid = leitor.int32()
            schema, tabela = leitor.texto(), leitor.texto()
            leitor.byte()  # replica identity
            colunas = []
            for _ in range(leitor.int16()):
                leitor.byte()  # flags: 1 se a coluna é da chave
                colunas.append(leitor.texto())
                leitor.int32()  # oid do tipo
                leitor.int32()  # typmod
            if schema != "public":
                raise CdcError(f"publicação entregou {schema}.{tabela}: só `public` é esperado")
            relacoes[relid] = (tabela, colunas)
        elif tipo == "I":
            relid = leitor.int32()
            leitor.byte()  # 'N'
            registrar(lsn, relid, "I", None, leitor.tupla(relacoes[relid][1]))
        elif tipo == "U":
            relid = leitor.int32()
            colunas = relacoes[relid][1]
            marcador, antes = leitor.byte(), None
            if marcador in ("K", "O"):
                antes = leitor.tupla(colunas)
                marcador = leitor.byte()
            depois = _preencher_nao_alterados(leitor.tupla(colunas), antes)
            registrar(lsn, relid, "U", antes, depois)
        elif tipo == "D":
            relid = leitor.int32()
            leitor.byte()  # 'K' ou 'O'
            registrar(lsn, relid, "D", leitor.tupla(relacoes[relid][1]), None)
        elif tipo == "T":
            quantidade = leitor.int32()
            leitor.byte()  # flags (CASCADE, RESTART IDENTITY)
            for _ in range(quantidade):
                registrar(lsn, leitor.int32(), "T", None, None)
        # Tipo (Y), origem (O) e mensagem lógica (M) não alteram dado nenhum.
    return mudancas, fim


# --- LGPD --------------------------------------------------------------------------


def hash_estabelecimento(cnpj: str, chave: str) -> str:
    return hmac.new(chave.encode("utf-8"), cnpj.encode("utf-8"), hashlib.sha256).hexdigest()


def _sem_dado_pessoal(tabela: str, valores: dict | None, chave: str) -> dict | None:
    if valores is None or tabela != "lojista":
        return valores
    limpos = {coluna: valor for coluna, valor in valores.items() if coluna in COLUNAS_LOJISTA}
    if valores.get("cnpj") is not None:
        limpos["hash_estabelecimento"] = hash_estabelecimento(str(valores["cnpj"]), chave)
    return limpos


def _para_linha(mudanca: dict, chave: str) -> dict:
    """Mudança decodificada -> linha da Bronze: sem dado pessoal, com a linha em JSON."""
    tabela = mudanca["tabela"]
    antes = _sem_dado_pessoal(tabela, mudanca["antes"], chave)
    depois = _sem_dado_pessoal(tabela, mudanca["depois"], chave)
    id_texto = (depois or antes or {}).get("id")
    return mudanca | {
        "id_registro": int(id_texto) if id_texto is not None else None,
        "antes": None if antes is None else json.dumps(antes, ensure_ascii=False, sort_keys=True),
        "depois": None
        if depois is None
        else json.dumps(depois, ensure_ascii=False, sort_keys=True),
    }


# --- Slot e gravação ---------------------------------------------------------------


def _preparar_slot(conexao: psycopg.Connection, slot: str) -> int | None:
    """Cria o slot na primeira execução e devolve o LSN inicial; ``None`` se ele já existia."""
    (wal_level,) = conexao.execute("show wal_level").fetchone()
    if wal_level != "logical":
        raise CdcError(f"wal_level={wal_level}: suba o banco com wal_level=logical (compose)")
    existente = conexao.execute(
        "select wal_status from pg_replication_slots where slot_name = %s", (slot,)
    ).fetchone()
    if existente is None:
        conexao.execute("select pg_create_logical_replication_slot(%s, 'pgoutput')", (slot,))
        (lsn,) = conexao.execute(
            "select (confirmed_flush_lsn - '0/0')::bigint from pg_replication_slots"
            " where slot_name = %s",
            (slot,),
        ).fetchone()
        return lsn
    if existente[0] == "lost":
        raise CdcError(
            f"o slot {slot} ficou parado além de max_slot_wal_keep_size e perdeu WAL: apague-o"
            f" (pg_drop_replication_slot) e rode de novo para refazer a foto das tabelas"
        )
    return None


def _ler_foto(conexao: psycopg.Connection, lsn: int) -> Iterator[dict]:
    """Uma mudança ``'r'`` por linha existente, com os valores em texto, como no pgoutput."""
    agora = datetime.now(UTC)
    for tabela in TABELAS:
        identificador = sql.Identifier("public", tabela)
        with conexao.cursor() as cursor:
            cursor.execute(sql.SQL("select * from {} limit 0").format(identificador))
            colunas = [coluna.name for coluna in cursor.description]
            selecao = sql.SQL(", ").join(
                sql.SQL("{}::text").format(sql.Identifier(coluna)) for coluna in colunas
            )
            cursor.execute(sql.SQL("select {} from {}").format(selecao, identificador))
            for linha in cursor:
                yield {
                    "lsn": lsn,
                    "lsn_commit": lsn,
                    "id_transacao": 0,
                    "tabela": tabela,
                    "operacao": "r",
                    "antes": None,
                    "depois": dict(zip(colunas, linha, strict=True)),
                    "commit_em": agora,
                }


def _gravar(destino: Path, mudancas: Iterable[dict], slot: str, chave: str) -> tuple[int, int]:
    requisicao = f"pg_logical_slot_peek_binary_changes:{slot}:{PUBLICACAO}"
    agora = datetime.now(UTC)
    linhas = []
    for mudanca in mudancas:
        linha = _para_linha(mudanca, chave)
        linha |= {
            "_id_resposta": bronze.hash_do_corpo(f"{slot}/{mudanca['lsn_commit']}"),
            "_fonte": FONTE,
            "_requisicao": requisicao,
            "_ingerido_em": agora,
        }
        linhas.append(linha)
    novas = bronze.acrescentar(destino, TABELA_DELTA, linhas, ESQUEMA_MUDANCA, CHAVE_MUDANCA)
    return len(linhas), novas


def capturar(
    conexao: psycopg.Connection,
    destino: Path,
    chave: str,
    *,
    slot: str = SLOT_PADRAO,
    publicacao: str = PUBLICACAO,
    avancar: bool = True,
) -> Captura:
    """Um ciclo de captura. A conexão precisa estar em ``autocommit``.

    ``avancar=False`` para depois de gravar, sem avançar o slot: é o que acontece quando o
    processo cai naquele ponto, e serve para demonstrar o reprocessamento.
    """
    if not chave:
        raise CdcError(f"defina {VARIAVEL_CHAVE} (ver .env.example): é o que protege o CNPJ")

    lidas = novas = 0
    lsn_inicial = _preparar_slot(conexao, slot)
    foto = lsn_inicial is not None
    if foto:
        try:
            lidas, novas = _gravar(destino, _ler_foto(conexao, lsn_inicial), slot, chave)
        except Exception:
            # Slot sem foto perderia o estado inicial para sempre: melhor recomeçar do zero.
            conexao.execute("select pg_drop_replication_slot(%s)", (slot,))
            raise

    while True:
        mensagens = conexao.execute(
            "select (lsn - '0/0')::bigint, xid::text::bigint, data"
            " from pg_logical_slot_peek_binary_changes(%s, null, %s,"
            " 'proto_version', '1', 'publication_names', %s)",
            (slot, MUDANCAS_POR_LOTE, publicacao),
        ).fetchall()
        if not mensagens:
            break
        mudancas, fim = decodificar(mensagens)
        lote_lidas, lote_novas = _gravar(destino, mudancas, slot, chave)
        lidas, novas = lidas + lote_lidas, novas + lote_novas
        if not avancar:
            break
        if fim is not None:
            conexao.execute(
                "select pg_replication_slot_advance(%s, %s::pg_lsn)",
                (slot, _texto_lsn(fim)),
            )
    return Captura(lidas, novas, foto)


def _texto_lsn(lsn: int) -> str:
    return f"{lsn >> 32:X}/{lsn & 0xFFFFFFFF:X}"


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dsn", default=None, help="padrão: montado do .env")
    parser.add_argument("--parquet-dir", default=DIRETORIO_PADRAO)
    parser.add_argument("--slot", default=SLOT_PADRAO)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        with psycopg.connect(
            args.dsn or dsn_do_ambiente(), autocommit=True, connect_timeout=5
        ) as conexao:
            captura = capturar(
                conexao,
                Path(args.parquet_dir),
                os.environ.get(VARIAVEL_CHAVE, ""),
                slot=args.slot,
            )
    except (CdcError, psycopg.Error) as erro:
        logger.error("captura interrompida, o slot não avançou além do que foi gravado: %s", erro)
        return 1
    logger.info(
        "CDC: %d mudanças lidas, %d novas%s",
        captura.lidas,
        captura.novas,
        " (primeira execução: inclui a foto das tabelas)" if captura.foto else "",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
