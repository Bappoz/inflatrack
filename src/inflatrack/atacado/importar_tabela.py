"""Importa a tabela de preços de um atacadista (CSV) direto no Postgres, schema `atacado`.

O preço não passa por Raw, Bronze, Silver nem Gold (ADR 0004). O CSV tem o cabeçalho
``produto;unidade;preco;codigo_subitem_ipca;vigente_desde`` (``;`` ou ``,``), preço em formato
brasileiro e data ``AAAA-MM-DD`` ou ``DD/MM/AAAA``.

Reimportar o mesmo arquivo não grava nada: um preço só vira linha nova quando muda em relação ao
que vigorava na data. A tabela é insert-only, então corrigir um preço exige uma data nova.

Uso::

    uv run python -m inflatrack.atacado.importar_tabela --arquivo data/atacado/tabela_exemplo.csv \
        --fornecedor "Atacadista Exemplo" --ficticio
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from inflatrack.common.conversores import converter_centavos, converter_data
from inflatrack.common.db import dsn_do_ambiente

logger = logging.getLogger("inflatrack.atacado")

COLUNAS = ("produto", "unidade", "preco", "codigo_subitem_ipca", "vigente_desde")
BRASILIA = 5300108


class SubitemAusente(ValueError):
    """O CSV cita subitens do IPCA que ainda não estão em `classificacao`."""


@dataclass(frozen=True)
class LinhaPreco:
    produto: str
    unidade: str
    preco_centavos: int
    codigo_subitem_ipca: str
    vigente_desde: date


@dataclass(frozen=True)
class Resultado:
    produtos_novos: int
    precos_novos: int


def ler_csv(conteudo: str) -> list[LinhaPreco]:
    """Valida o arquivo inteiro antes de devolver qualquer linha."""
    conteudo = conteudo.lstrip("﻿")
    primeira = conteudo.split("\n", 1)[0]
    leitor = csv.DictReader(io.StringIO(conteudo), delimiter=";" if ";" in primeira else ",")
    cabecalho = {(campo or "").strip().lower() for campo in leitor.fieldnames or []}
    faltando = [coluna for coluna in COLUNAS if coluna not in cabecalho]
    if faltando:
        raise ValueError(f"colunas ausentes no CSV: {', '.join(faltando)}")

    linhas: list[LinhaPreco] = []
    vistos: dict[tuple[str, date], int] = {}
    for numero, bruta in enumerate(leitor, start=2):
        campos = {(k or "").strip().lower(): (v or "").strip() for k, v in bruta.items()}
        try:
            linha = LinhaPreco(
                produto=_obrigatorio(campos, "produto"),
                unidade=_obrigatorio(campos, "unidade"),
                preco_centavos=converter_centavos(campos["preco"]),
                codigo_subitem_ipca=_obrigatorio(campos, "codigo_subitem_ipca"),
                vigente_desde=converter_data(campos["vigente_desde"]),
            )
        except ValueError as erro:
            raise ValueError(f"linha {numero}: {erro}") from erro
        if linha.preco_centavos == 0:
            raise ValueError(f"linha {numero}: preço zero")
        chave = (linha.produto, linha.vigente_desde)
        if chave in vistos and vistos[chave] != linha.preco_centavos:
            raise ValueError(
                f"linha {numero}: {linha.produto} aparece com dois preços em {linha.vigente_desde}"
            )
        if chave not in vistos:
            vistos[chave] = linha.preco_centavos
            linhas.append(linha)
    if not linhas:
        raise ValueError("o CSV não tem nenhuma linha de preço")
    return linhas


def _obrigatorio(campos: dict[str, str], coluna: str) -> str:
    if not campos.get(coluna):
        raise ValueError(f"{coluna} vazio")
    return campos[coluna]


def importar(
    conexao: psycopg.Connection,
    linhas: list[LinhaPreco],
    fornecedor: str,
    codigo_localidade: int,
    ficticio: bool,
) -> Resultado:
    """Grava numa transação só: ou o arquivo inteiro entra, ou nada entra."""
    with conexao.transaction():
        _conferir_subitens(conexao, {linha.codigo_subitem_ipca for linha in linhas})
        conexao.execute(
            "insert into atacado.fornecedor (nome, codigo_localidade, ficticio)"
            " values (%s, %s, %s) on conflict (nome) do nothing",
            (fornecedor, codigo_localidade, ficticio),
        )
        (id_fornecedor,) = conexao.execute(
            "select id from atacado.fornecedor where nome = %s", (fornecedor,)
        ).fetchone()

        produtos_novos = precos_novos = 0
        for linha in linhas:
            id_produto, novo = _produto(conexao, id_fornecedor, linha)
            produtos_novos += novo
            precos_novos += _preco(conexao, id_produto, linha)
    return Resultado(produtos_novos=produtos_novos, precos_novos=precos_novos)


def _conferir_subitens(conexao: psycopg.Connection, codigos: set[str]) -> None:
    existentes = {
        codigo
        for (codigo,) in conexao.execute(
            "select codigo from classificacao where codigo = any(%s)", (list(codigos),)
        )
    }
    ausentes = sorted(codigos - existentes)
    if ausentes:
        raise SubitemAusente(
            f"subitens do IPCA ausentes em classificacao: {', '.join(ausentes)}."
            " Rode a carga do IPCA no Postgres antes (just seed-amostra ou just seed)."
        )


def _produto(conexao: psycopg.Connection, id_fornecedor: int, linha: LinhaPreco) -> tuple[int, int]:
    criado = conexao.execute(
        "insert into atacado.produto (id_fornecedor, nome, unidade, codigo_subitem_ipca)"
        " values (%s, %s, %s, %s) on conflict (id_fornecedor, nome) do nothing returning id",
        (id_fornecedor, linha.produto, linha.unidade, linha.codigo_subitem_ipca),
    ).fetchone()
    if criado:
        return criado[0], 1
    (id_produto,) = conexao.execute(
        "select id from atacado.produto where id_fornecedor = %s and nome = %s",
        (id_fornecedor, linha.produto),
    ).fetchone()
    return id_produto, 0


def _preco(conexao: psycopg.Connection, id_produto: int, linha: LinhaPreco) -> int:
    """1 se gravou um preço novo, 0 se o preço vigente na data já é este."""
    vigente = conexao.execute(
        "select preco_centavos, vigente_desde from atacado.preco"
        " where id_produto = %s and vigente_desde <= %s"
        " order by vigente_desde desc limit 1",
        (id_produto, linha.vigente_desde),
    ).fetchone()
    if vigente and vigente[0] == linha.preco_centavos:
        return 0
    if vigente and vigente[1] == linha.vigente_desde:
        raise ValueError(
            f"{linha.produto} já tem outro preço em {linha.vigente_desde}; o histórico é"
            " insert-only, registre a correção com uma data nova"
        )
    conexao.execute(
        "insert into atacado.preco (id_produto, preco_centavos, vigente_desde) values (%s, %s, %s)",
        (id_produto, linha.preco_centavos, linha.vigente_desde),
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--arquivo", type=Path, required=True)
    parser.add_argument("--fornecedor", required=True)
    parser.add_argument("--localidade", type=int, default=BRASILIA)
    parser.add_argument("--ficticio", action="store_true", help="marca o atacadista como inventado")
    parser.add_argument("--dsn", default=None, help="padrão: montado do .env")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        linhas = ler_csv(args.arquivo.read_text(encoding="utf-8"))
        with psycopg.connect(args.dsn or dsn_do_ambiente(), connect_timeout=5) as conexao:
            resultado = importar(conexao, linhas, args.fornecedor, args.localidade, args.ficticio)
    except (OSError, ValueError, psycopg.Error) as erro:
        logger.error("importação interrompida: %s", erro)
        return 1
    logger.info(
        "%s: %d linhas lidas, %d produtos novos, %d preços novos",
        args.fornecedor,
        len(linhas),
        resultado.produtos_novos,
        resultado.precos_novos,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
