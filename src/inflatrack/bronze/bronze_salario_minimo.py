"""Bronze do Salário Mínimo (DIEESE): tabela de respostas e tabela extraída, em Delta.

Cada requisição da página do DIEESE vira duas coisas, gravadas no mesmo passo::

    data/parquet/salario_minimo/resposta/  salario_minimo_resposta  uma por resposta
    data/parquet/salario_minimo/mes/       salario_minimo_mes       uma por mês histórico

``salario_minimo_resposta`` guarda o HTML inteiro e substitui os ``.html.gz`` de
``data/raw/dieese/``.
``salario_minimo_mes`` é a entrada do DuckDB e do dbt: tipada, com TODAS as linhas da tabela HTML,
sem descartar meses e sem a coluna calculada (``multiplo_necessario_nominal``). Cálculos e regras de
negócio são delegados para o dbt.

As duas tabelas só acrescentam. Reexecutar com a mesma página não grava nada; se o DIEESE
revisar um valor histórico, a revisão entra como linha nova e a anterior permanece (semântica
*insert-only*).

Uso::

    uv run python -m inflatrack.bronze_salario_minimo ingest
    uv run python -m inflatrack.bronze_salario_minimo checar
    uv run python -m inflatrack.bronze_salario_minimo importar --raw-dir data/raw/dieese
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import logging
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as ds
from deltalake import DeltaTable, write_deltalake

from inflatrack import dieese

logger = logging.getLogger("inflatrack.bronze_salario_minimo")

FONTE = "salario_minimo"
DIRETORIO_PADRAO = "data/parquet/salario_minimo"

TIPO_VALOR = pa.decimal128(12, 2)

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

ESQUEMA_MES = pa.schema(
    [
        pa.field("ano_mes", pa.string(), nullable=False),
        pa.field("data_referencia", pa.date32(), nullable=False),
        pa.field("ano", pa.int16(), nullable=False),
        pa.field("mes", pa.int16(), nullable=False),
        pa.field("salario_nominal", TIPO_VALOR, nullable=True),
        pa.field("salario_necessario", TIPO_VALOR, nullable=True),
        pa.field("_id_resposta", pa.string(), nullable=False),
        pa.field("_fonte", pa.string(), nullable=False),
        pa.field("_requisicao", pa.string(), nullable=False),
        pa.field("_ingerido_em", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

CHAVE_MES = (
    "ano_mes",
    "salario_nominal",
    "salario_necessario",
)

DATA_INICIO_ESPERADA = date(1994, 7, 1)
VOLUME_MINIMO_REFERENCIA = 387


class ChecagemError(ValueError):
    """A resposta não tem a forma esperada e não deve ser promovida à Bronze."""


@dataclass(frozen=True)
class Gravacao:
    """O que uma chamada de :func:`gravar` acrescentou de fato."""

    id_resposta: str
    resposta_nova: bool
    linhas_lidas: int
    linhas_novas: int


def hash_do_corpo(corpo: str) -> str:
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()


def _limpar_moeda(valor_str: str) -> Decimal | None:
    """Converte 'R$ 1.621,00' para Decimal('1621.00')."""
    texto_limpo = re.sub(r"[^\d,]", "", valor_str).replace(",", ".")
    if not texto_limpo:
        return None
    try:
        return Decimal(texto_limpo)
    except InvalidOperation as erro:
        raise ChecagemError(f"Valor monetário inválido: {valor_str!r}") from erro


def transformar(html_conteudo: str) -> list[dict]:
    """Extrai todas as linhas da tabela HTML do DIEESE em dicionários tipados.

    Não descarta meses e não calcula o múltiplo necessário/nominal (regra de negócio para o dbt).
    """
    match_tabela = re.search(r"<table[^>]*>(.*?)</table>", html_conteudo, re.DOTALL | re.IGNORECASE)
    if not match_tabela:
        raise ChecagemError("Nenhuma tabela encontrada no conteúdo HTML fornecido.")

    conteudo_tabela = match_tabela.group(1)
    linhas = re.findall(r"<tr([^>]*)>(.*?)</tr>", conteudo_tabela, re.DOTALL | re.IGNORECASE)
    if not linhas:
        raise ChecagemError("A tabela HTML não contém linhas <tr>.")

    registros: list[dict] = []
    ano_vigente: int | None = None

    for attrs, linha in linhas:
        if "subtitulo" in attrs.lower():
            match_ano = re.search(r"(\d{4})", linha)
            if match_ano:
                ano_vigente = int(match_ano.group(1))
            continue

        colunas = re.findall(r"<td[^>]*>(.*?)</td>", linha, re.DOTALL | re.IGNORECASE)
        if len(colunas) < 3:
            if len(colunas) == 1:
                match_ano = re.search(r"^\s*(\d{4})\s*$", re.sub(r"<.*?>", "", colunas[0]))
                if match_ano:
                    ano_vigente = int(match_ano.group(1))
            continue
        if ano_vigente is None:
            continue

        mes_texto = html.unescape(re.sub(r"<.*?>", "", colunas[0])).strip().lower()
        if mes_texto not in dieese.MAPA_MESES:
            continue

        mes_num = dieese.MAPA_MESES[mes_texto]
        salario_nom = _limpar_moeda(colunas[1])
        salario_nec = _limpar_moeda(colunas[2])

        ano_mes = f"{ano_vigente:04d}-{mes_num:02d}"
        data_ref = date(ano_vigente, mes_num, 1)

        registros.append(
            {
                "ano_mes": ano_mes,
                "data_referencia": data_ref,
                "ano": ano_vigente,
                "mes": mes_num,
                "salario_nominal": salario_nom,
                "salario_necessario": salario_nec,
            }
        )

    if not registros:
        raise ChecagemError("Nenhum registro extraído da tabela HTML.")

    registros.sort(key=lambda r: r["data_referencia"])
    return registros


def _meses_no_intervalo(inicio: date, fim: date) -> list[date]:
    """Gera a sequência contínua de primeiros dias de cada mês entre inicio e fim."""
    resultado = []
    ano, mes = inicio.year, inicio.month
    fim_ano, fim_mes = fim.year, fim.month
    while (ano, mes) <= (fim_ano, fim_mes):
        resultado.append(date(ano, mes, 1))
        mes += 1
        if mes > 12:
            mes = 1
            ano += 1
    return resultado


def checar(linhas: list[dict]) -> None:
    """Checagens de esquema, volume e continuidade da série antes de gravar."""
    if not linhas:
        raise ChecagemError("Série de salário mínimo vazia.")

    anos_meses = [linha["ano_mes"] for linha in linhas]
    if len(anos_meses) != len(set(anos_meses)):
        duplicados = [am for am in anos_meses if anos_meses.count(am) > 1]
        raise ChecagemError(f"Meses duplicados encontrados: {sorted(set(duplicados))}")

    primeiro_mes = linhas[0]["data_referencia"]
    if primeiro_mes != DATA_INICIO_ESPERADA:
        raise ChecagemError(
            f"Série deve iniciar em {DATA_INICIO_ESPERADA:%Y-%m}, "
            f"mas iniciou em {primeiro_mes:%Y-%m}"
        )

    ultimo_mes = linhas[-1]["data_referencia"]
    esperados = _meses_no_intervalo(primeiro_mes, ultimo_mes)
    existentes = {linha["data_referencia"] for linha in linhas}
    faltando = [d for d in esperados if d not in existentes]
    if faltando:
        raise ChecagemError(
            f"Buraco na série temporal: {len(faltando)} meses faltando entre {primeiro_mes:%Y-%m} "
            f"e {ultimo_mes:%Y-%m}: {[d.strftime('%Y-%m') for d in faltando[:5]]}"
        )

    if len(linhas) < VOLUME_MINIMO_REFERENCIA:
        raise ChecagemError(
            f"Volume de registros ({len(linhas)}) inferior ao mínimo de referência "
            f"({VOLUME_MINIMO_REFERENCIA})"
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
    """Guarda o HTML da resposta em Delta, evitando duplicatas por hash_corpo."""
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
    return tuple(linha[coluna] for coluna in CHAVE_MES)


def _chaves_existentes(caminho: str) -> set[tuple]:
    if not DeltaTable.is_deltatable(caminho):
        return set()
    tabela = DeltaTable(caminho).to_pyarrow_dataset().to_table(columns=list(CHAVE_MES))
    colunas = [tabela.column(coluna).to_pylist() for coluna in CHAVE_MES]
    return set(zip(*colunas, strict=True))


def acrescentar_meses(destino: Path, linhas: list[dict]) -> int:
    """Acrescenta na tabela Delta apenas os meses novos ou revisados."""
    if not linhas:
        return 0
    caminho = _caminho(destino, "mes")
    existentes = _chaves_existentes(caminho)
    novas = [linha for linha in linhas if _chave(linha) not in existentes]
    if novas:
        write_deltalake(
            caminho,
            pa.Table.from_pylist(novas, ESQUEMA_MES),
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
    html_conteudo: str,
    requisicao: str = dieese.DIEESE_URL,
    ingerido_em: datetime | None = None,
    status_http: int | None = 200,
    tipo_conteudo: str | None = "text/html; charset=ISO-8859-1",
) -> Gravacao:
    """Executa a transformação, validação e gravação nas duas tabelas Delta."""
    ingerido_em = ingerido_em or datetime.now(UTC)
    linhas = transformar(html_conteudo)
    checar(linhas)

    id_resposta, nova = gravar_resposta(
        destino,
        requisicao=requisicao,
        corpo=html_conteudo,
        ingerido_em=ingerido_em,
        status_http=status_http,
        tipo_conteudo=tipo_conteudo,
    )
    novas = acrescentar_meses(destino, _com_metadados(linhas, id_resposta, requisicao, ingerido_em))
    return Gravacao(id_resposta, nova, len(linhas), novas)


def importar_raw(
    raw_dir: Path,
    destino: Path,
) -> tuple[int, int, list[str]]:
    """Importa arquivos .html.gz de data/raw/dieese/ para as duas tabelas Delta."""
    respostas = meses_novos = 0
    falhas: list[str] = []

    for caminho in sorted(raw_dir.glob("*.html.gz")):
        try:
            with gzip.open(caminho, "rt", encoding="utf-8", errors="replace") as f:
                corpo = f.read()
            ingerido_em = datetime.fromtimestamp(caminho.stat().st_mtime, UTC)
            grav = gravar(
                destino,
                html_conteudo=corpo,
                requisicao=dieese.DIEESE_URL,
                ingerido_em=ingerido_em,
                status_http=None,
                tipo_conteudo=None,
            )
            respostas += int(grav.resposta_nova)
            meses_novos += grav.linhas_novas
        except Exception as erro:
            falhas.append(f"{caminho.name}: {erro}")

    return respostas, meses_novos, falhas


def checar_tabela(destino: Path) -> dict:
    """Inspeciona a tabela salario_minimo_mes gravada em Delta."""
    caminho = _caminho(destino, "mes")
    if not DeltaTable.is_deltatable(caminho):
        raise ChecagemError(f"Tabela Delta não encontrada em {caminho}")

    dt = DeltaTable(caminho)
    tbl = dt.to_pyarrow_table()
    linhas = tbl.to_pylist()
    checar(linhas)

    primeiro_mes = linhas[0]["data_referencia"]
    ultimo_mes = linhas[-1]["data_referencia"]
    return {
        "linhas": len(linhas),
        "primeiro_mes": str(primeiro_mes),
        "ultimo_mes": str(ultimo_mes),
        "versoes": dt.version(),
    }


def carregar_duckdb(
    destino: Path,
    db_caminho: Path | str = "data/duckdb/inflatrack.duckdb",
    modo: str = "substitui",
) -> int:
    """Carrega a tabela Delta salario_minimo_mes no DuckDB nos dois modos do contrato."""
    import duckdb

    from inflatrack import load_salario_minimo

    db = Path(db_caminho)
    db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db)) as conexao:
        return load_salario_minimo.carregar_bronze(conexao, destino, modo=modo)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="comando", required=True)

    p_ingest = subparsers.add_parser("ingest", help="Baixa da API e grava em Delta")
    p_ingest.add_argument("--destino", default=DIRETORIO_PADRAO)

    p_checar = subparsers.add_parser("checar", help="Verifica a tabela Delta gravada")
    p_checar.add_argument("--destino", default=DIRETORIO_PADRAO)

    p_importar = subparsers.add_parser("importar", help="Importa do raw antigo")
    p_importar.add_argument("--raw-dir", default="data/raw/dieese")
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
    if args.comando == "ingest":
        logger.info("Baixando página de salário mínimo do DIEESE...")
        conteudo = dieese.baixar_html()
        grav = gravar(destino, conteudo)
        logger.info(
            "Gravado com sucesso: resposta %s, %d de %d meses novos",
            "nova" if grav.resposta_nova else "já guardada",
            grav.linhas_novas,
            grav.linhas_lidas,
        )
        return 0
    if args.comando == "checar":
        try:
            info = checar_tabela(destino)
            print(
                f"salario_minimo_mes linhas={info['linhas']} primeiro_mes={info['primeiro_mes']} "
                f"ultimo_mes={info['ultimo_mes']} versoes={info['versoes']} status=OK"
            )
            return 0
        except ChecagemError as erro:
            logger.error("Checagem falhou: %s", erro)
            return 1
    if args.comando == "importar":
        respostas, novas, falhas = importar_raw(Path(args.raw_dir), destino)
        logger.info(
            "Importação: %d respostas novas, %d meses novos, %d falhas",
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
            "Carga no DuckDB concluída (%s): %d meses em bronze.salario_minimo_mes",
            args.modo,
            total,
        )
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
