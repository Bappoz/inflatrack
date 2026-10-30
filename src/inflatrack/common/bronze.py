"""Helper comum da Bronze: tabela de respostas, tabela extraída e carga no DuckDB.

Cada fonte grava, no mesmo passo, duas tabelas Delta em ``data/parquet/<base>/``

    resposta/   <base>_resposta   uma linha por resposta DIFERENTE da fonte
    <tabela>/   <base>_<tabela>   uma linha por registro extraído da resposta

A tabela de respostas só acrescenta e nunca repete um corpo (o id é o SHA-256 do
corpo). A tabela extraída tem dois modos, escolhidos pela fonte:

* :func:`acrescentar` — só acrescenta o que é novo, com o valor na chave. Para fonte
  que revisa valor publicado: a revisão vira linha nova e a anterior permanece.
* :func:`substituir_particao` — troca a partição inteira numa única versão do Delta.
  Para série que chega completa a cada chamada.

:func:`carregar_duckdb` espelha a tabela extraída em ``bronze.<base>_<tabela>`` com os
mesmos dois modos, sem transformar nada (seção 2.3).
"""

from __future__ import annotations

import gzip
import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import pyarrow as pa
import pyarrow.dataset as ds
from deltalake import DeltaTable, write_deltalake

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

# As quatro colunas de linhagem que toda tabela extraída carrega, no fim do esquema.
CAMPOS_METADADOS = [
    pa.field("_id_resposta", pa.string(), nullable=False),
    pa.field("_fonte", pa.string(), nullable=False),
    pa.field("_requisicao", pa.string(), nullable=False),
    pa.field("_ingerido_em", pa.timestamp("us", tz="UTC"), nullable=False),
]


class ChecagemError(ValueError):
    """A resposta não tem a forma esperada e não deve ser promovida à Bronze."""


@dataclass(frozen=True)
class Resposta:
    """Resposta HTTP como chegou, antes de qualquer interpretação."""

    url: str
    status_http: int | None
    tipo_conteudo: str | None
    corpo: str


def esquema_extraido(campos: Sequence[pa.Field]) -> pa.Schema:
    """Esquema da tabela extraída: os campos da fonte seguidos dos metadados."""
    return pa.schema([*campos, *CAMPOS_METADADOS])


def hash_do_corpo(corpo: str) -> str:
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()


def caminho(destino: Path, tabela: str) -> str:
    return str(Path(destino) / tabela)


def ler_gz(arquivo: Path) -> str:
    """Texto de um ``.json.gz`` / ``.html.gz`` do Raw antigo, para importação."""
    with gzip.open(arquivo, "rt", encoding="utf-8") as entrada:
        return entrada.read()


def gravar_resposta(
    destino: Path,
    fonte: str,
    resposta: Resposta,
    ingerido_em: datetime,
) -> tuple[str, bool]:
    """Guarda o corpo da resposta, a menos que um corpo idêntico já esteja guardado.

    Devolve ``(id_resposta, nova)``. O id é o SHA-256 do corpo, então a tabela tem
    exatamente uma linha por versão diferente que a fonte publicou.
    """
    alvo = caminho(destino, "resposta")
    id_resposta = hash_do_corpo(resposta.corpo)
    if DeltaTable.is_deltatable(alvo):
        existentes = (
            DeltaTable(alvo)
            .to_pyarrow_dataset()
            .to_table(columns=["hash_corpo"], filter=ds.field("hash_corpo") == id_resposta)
        )
        if existentes.num_rows:
            return id_resposta, False

    linha = {
        "id_resposta": id_resposta,
        "_fonte": fonte,
        "_requisicao": resposta.url,
        "_ingerido_em": ingerido_em,
        "status_http": resposta.status_http,
        "tipo_conteudo": resposta.tipo_conteudo,
        "corpo": resposta.corpo,
        "hash_corpo": id_resposta,
        "tamanho_bytes": len(resposta.corpo.encode("utf-8")),
    }
    write_deltalake(alvo, pa.Table.from_pylist([linha], ESQUEMA_RESPOSTA), mode="append")
    return id_resposta, True


def com_metadados(
    linhas: Iterable[dict], *, id_resposta: str, fonte: str, requisicao: str, ingerido_em: datetime
) -> list[dict]:
    metadados = {
        "_id_resposta": id_resposta,
        "_fonte": fonte,
        "_requisicao": requisicao,
        "_ingerido_em": ingerido_em,
    }
    return [linha | metadados for linha in linhas]


def _chaves_existentes(alvo: str, chave: Sequence[str]) -> set[tuple]:
    if not DeltaTable.is_deltatable(alvo):
        return set()
    tabela = DeltaTable(alvo).to_pyarrow_dataset().to_table(columns=list(chave))
    colunas = [tabela.column(coluna).to_pylist() for coluna in chave]
    return set(zip(*colunas, strict=True))


def acrescentar(
    destino: Path,
    tabela: str,
    linhas: list[dict],
    esquema: pa.Schema,
    chave: Sequence[str],
    partition_by: list[str] | None = None,
) -> int:
    """Acrescenta só as linhas cuja ``chave`` ainda não existe e devolve quantas entraram.

    Ponha o valor na chave: linha igual é ignorada (reexecução sem efeito) e valor
    diferente para o mesmo registro é revisão e entra como linha nova.
    """
    if not linhas:
        return 0
    alvo = caminho(destino, tabela)
    existentes = _chaves_existentes(alvo, chave)
    novas, vistas = [], set(existentes)
    for linha in linhas:
        identidade = tuple(linha[coluna] for coluna in chave)
        if identidade not in vistas:
            vistas.add(identidade)
            novas.append(linha)
    if novas:
        write_deltalake(
            alvo,
            pa.Table.from_pylist(novas, esquema),
            mode="append",
            partition_by=partition_by,
        )
    return len(novas)


def _literal_sql(valor: object) -> str:
    if isinstance(valor, str):
        return "'" + valor.replace("'", "''") + "'"
    if isinstance(valor, bool) or valor is None:
        raise TypeError(f"valor de partição não suportado: {valor!r}")
    return str(valor)


def substituir_particao(
    destino: Path,
    tabela: str,
    linhas: list[dict],
    esquema: pa.Schema,
    particao: dict[str, object],
) -> int:
    """Troca todas as linhas da partição ``particao`` por ``linhas``, num único commit.

    A partição é também a coluna de ``partition_by`` do Delta. Toda linha precisa
    pertencer à partição: o Delta recusa a escrita se alguma ficar fora do predicado.
    """
    if not linhas:
        raise ChecagemError(f"{tabela}: substituir a partição {particao} por nada apagaria dados")
    predicado = " AND ".join(
        f"{coluna} = {_literal_sql(valor)}" for coluna, valor in particao.items()
    )
    write_deltalake(
        caminho(destino, tabela),
        pa.Table.from_pylist(linhas, esquema),
        mode="overwrite",
        predicate=predicado,
        partition_by=list(particao),
    )
    return len(linhas)


def ler(destino: Path, tabela: str) -> pa.Table:
    alvo = caminho(destino, tabela)
    if not DeltaTable.is_deltatable(alvo):
        raise ChecagemError(f"não há tabela Delta em {alvo}")
    return DeltaTable(alvo).to_pyarrow_table()


def versao(destino: Path, tabela: str) -> int | None:
    alvo = caminho(destino, tabela)
    return DeltaTable(alvo).version() if DeltaTable.is_deltatable(alvo) else None


# --- Delta -> DuckDB ---------------------------------------------------------------


def carregar_duckdb(
    conexao,
    origem: pa.Table,
    tabela: str,
    modo: Literal["acrescenta", "substitui"],
    colunas: Sequence[str],
) -> int:
    """Espelha ``origem`` em ``tabela`` do DuckDB, sem transformar. Devolve linhas inseridas.

    * ``acrescenta``: insere só as linhas cuja combinação ``colunas`` (a chave, com o
      valor dentro) ainda não está na tabela.
    * ``substitui``: apaga da tabela as partições ``colunas`` presentes em ``origem`` e
      insere ``origem`` inteira.

    A tabela é criada com o esquema de ``origem`` se ainda não existir; quem quiser
    tipos próprios cria antes, pelo ``setup_duckdb_<base>.sql``. Tudo numa transação.
    """
    if modo not in ("acrescenta", "substitui"):
        raise ValueError(f"modo desconhecido: {modo}")
    conexao.register("_origem_bronze", origem)
    try:
        conexao.execute("BEGIN")
        conexao.execute(
            f"CREATE TABLE IF NOT EXISTS {tabela} AS SELECT * FROM _origem_bronze LIMIT 0"
        )
        antes = conexao.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]
        if modo == "substitui":
            lista = ", ".join(colunas)
            conexao.execute(
                f"DELETE FROM {tabela} "
                f"WHERE ({lista}) IN (SELECT DISTINCT {lista} FROM _origem_bronze)"
            )
            conexao.execute(f"INSERT INTO {tabela} SELECT * FROM _origem_bronze")
            inseridas = origem.num_rows
        else:
            iguais = " AND ".join(f"t.{c} IS NOT DISTINCT FROM o.{c}" for c in colunas)
            conexao.execute(
                f"INSERT INTO {tabela} SELECT o.* FROM _origem_bronze o "
                f"WHERE NOT EXISTS (SELECT 1 FROM {tabela} t WHERE {iguais})"
            )
            inseridas = conexao.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0] - antes
        conexao.execute("COMMIT")
    except Exception:
        conexao.execute("ROLLBACK")
        raise
    finally:
        conexao.unregister("_origem_bronze")
    return inseridas


def duplicadas(tabela: pa.Table, colunas: Sequence[str]) -> int:
    """Quantas linhas repetem uma combinação de ``colunas`` (0 = chave única)."""
    if tabela.num_rows == 0:
        return 0
    agrupado = tabela.group_by(list(colunas)).aggregate([([], "count_all")])
    return tabela.num_rows - agrupado.num_rows
