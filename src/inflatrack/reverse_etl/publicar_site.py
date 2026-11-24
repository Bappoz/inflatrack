"""Publica no Supabase o mínimo que o site e o agente precisam (ETL reverso para fora).

O site não acessa o ambiente local. Ele lê só estas cinco tabelas, criadas por
`web/backend/migrations/003_publicacao_inflatrack.sql`:

- `previsao_subitem`: a `gold.fct_previsao_subitem` (variação prevista e erro típico);
- `subitem`: nome e grupo de cada subitem, para a busca por produto;
- `uf_praca`: a praça do IPCA de cada UF (UF sem praça usa o Brasil);
- `resumo_subitem`: o IPCA do último mês, por praça e subitem (mês e 12 meses);
- `painel_grafico`: o resultado pronto de cada gráfico do painel do lojista do Metabase.

A previsão, os nomes e o resumo vêm da Gold (DuckDB, só leitura). Os gráficos rodam os SQLs de
`scripts/sql/metabase/` na `serie` do Postgres local, como o Metabase. Cada publicação apaga e
reescreve tudo numa transação: ou entra inteira, ou o site continua com a anterior. Nenhum preço
vai para o Supabase (ADR 0004).

Uso::

    uv run python -m inflatrack.reverse_etl.publicar_site   # exige SUPABASE_DB_URL no .env
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from inflatrack.common.db import DUCKDB_PADRAO, dsn_do_ambiente

logger = logging.getLogger("inflatrack.publicar_site")

RAIZ = Path(__file__).resolve().parents[3]
PAINEL = RAIZ / "scripts" / "sql" / "metabase" / "painel.toml"
VARIAVEL_DSN = "SUPABASE_DB_URL"
# Lista do que PODE ir (e não do que não pode): uma pergunta nova no painel, talvez com preço, só
# chega ao Supabase público se alguém a acrescentar aqui de propósito. O p5 (reajuste por produto
# do lojista) fica de fora: vira o formulário do chat do site.
PAINEL_DO_SITE = (
    "p1_inflacao_12m_por_setor",
    "p4_brasil_x_regiao",
    "p4_brasil_ipca_x_inpc_5_anos",
    "p2_sazonalidade_por_mes",
    "p3_poder_de_compra_desde_2006",
    "p3_salario_minimo_real",
)
# Coluna com cara de preço ou custo nunca vai para o Supabase (ADR 0004).
_COLUNA_DE_PRECO = re.compile(r"pre[cç]o|custo", re.IGNORECASE)

BRASIL = 1
PRACAS_IPCA = {
    BRASIL, 1501, 2301, 2601, 2901, 3101, 3201, 3301, 3501, 4101, 4301,
    1200401, 2111300, 2800308, 5002704, 5208707, 5300108,
}  # fmt: skip
UF_PRACA: dict[str, int] = {
    "PA": 1501, "CE": 2301, "PE": 2601, "BA": 2901, "MG": 3101, "ES": 3201,
    "RJ": 3301, "SP": 3501, "PR": 4101, "RS": 4301, "AC": 1200401, "MA": 2111300,
    "SE": 2800308, "MS": 5002704, "GO": 5208707, "DF": 5300108,
    # Sem praça no IPCA: o índice do Brasil.
    "AL": BRASIL, "AP": BRASIL, "AM": BRASIL, "MT": BRASIL, "PB": BRASIL, "PI": BRASIL,
    "RN": BRASIL, "RO": BRASIL, "RR": BRASIL, "SC": BRASIL, "TO": BRASIL,
}  # fmt: skip

_TABELAS = ("previsao_subitem", "subitem", "uf_praca", "resumo_subitem", "painel_grafico")


@dataclass
class Publicacao:
    previsao: pd.DataFrame
    subitem: pd.DataFrame
    uf_praca: pd.DataFrame
    resumo: pd.DataFrame
    painel: list[dict[str, Any]]


def perguntas_do_painel(caminho: Path = PAINEL) -> list[dict[str, Any]]:
    """As perguntas do painel do lojista que vão para o site, com `id` = nome do arquivo."""
    perguntas = tomllib.loads(caminho.read_text(encoding="utf-8"))["perguntas"]
    return [
        {**p, "id": p["arquivo"].removesuffix(".sql")}
        for p in perguntas
        if p["arquivo"].removesuffix(".sql") in PAINEL_DO_SITE
    ]


def conferir_sem_preco(id_grafico: str, linhas: list[dict[str, Any]]) -> None:
    """Segunda trava do ADR 0004: recusa gráfico com coluna de preço ou custo."""
    colunas = {coluna for linha in linhas for coluna in linha}
    suspeitas = sorted(c for c in colunas if _COLUNA_DE_PRECO.search(c))
    if suspeitas:
        raise ValueError(
            f"o gráfico {id_grafico} tem coluna de preço ({', '.join(suspeitas)}):"
            " preço não vai para o Supabase (ADR 0004)"
        )


def linhas_json(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Datas viram ISO e Decimal vira float, para caber no jsonb."""

    def converter(valor: Any) -> Any:
        if isinstance(valor, datetime | date):
            return valor.isoformat()[:10] if isinstance(valor, date) else valor.isoformat()
        if isinstance(valor, Decimal):
            return float(valor)
        return valor

    return [{chave: converter(valor) for chave, valor in linha.items()} for linha in linhas]


def coletar(caminho_duckdb: Path, dsn_local: str) -> Publicacao:
    with duckdb.connect(str(caminho_duckdb), read_only=True) as conexao:
        previsao = conexao.sql("select * from gold.fct_previsao_subitem").df()
        subitem = conexao.sql(
            """
            with cesta as (
                select codigo_categoria, nivel_categoria,
                       arg_max(nome_categoria, vigencia_inicio) as nome
                from gold.dim_cesta_ipca_scd2
                where indice = 'IPCA' and versao_atual
                group by all
            )
            select s.codigo_categoria as codigo_subitem, s.nome,
                   g.codigo_categoria as codigo_grupo, g.nome as nome_grupo
            from cesta s
            join cesta g on g.nivel_categoria = 'grupo'
                        and g.codigo_categoria = left(s.codigo_categoria, 1)
            where s.nivel_categoria = 'subitem'
            """
        ).df()
        resumo = conexao.sql(
            """
            select codigo_localidade, codigo_categoria as codigo_subitem, mes_referencia,
                   variacao_mensal_pct, variacao_acum_12m_pct as variacao_12m_pct
            from gold.fct_inflacao_mensal
            where indice = 'IPCA' and nivel_categoria = 'subitem'
              and mes_referencia = (
                  select max(mes_referencia) from gold.fct_inflacao_mensal where indice = 'IPCA'
              )
            """
        ).df()
        nomes = dict(
            conexao.sql(
                "select codigo_localidade, nome_localidade from gold.dim_localidade"
            ).fetchall()
        )
    uf_praca = pd.DataFrame(
        [(uf, codigo, nomes[codigo]) for uf, codigo in sorted(UF_PRACA.items())],
        columns=["uf", "codigo_localidade", "nome_praca"],
    )
    return Publicacao(
        previsao=previsao,
        subitem=subitem[subitem["codigo_subitem"].isin(previsao["codigo_subitem"])],
        uf_praca=uf_praca,
        resumo=resumo,
        painel=_painel(dsn_local),
    )


def _painel(dsn_local: str) -> list[dict[str, Any]]:
    graficos = []
    with psycopg.connect(dsn_local, connect_timeout=5, row_factory=dict_row) as conexao:
        for pergunta in perguntas_do_painel():
            sql = (PAINEL.parent / pergunta["arquivo"]).read_text(encoding="utf-8")
            linhas = linhas_json(conexao.execute(sql).fetchall())
            conferir_sem_preco(pergunta["id"], linhas)
            ate_o_mes = next((linha["ate_o_mes"] for linha in linhas if "ate_o_mes" in linha), None)
            graficos.append(
                {
                    "id": pergunta["id"],
                    "titulo": pergunta["titulo"],
                    "grafico": pergunta.get("grafico", "table"),
                    "eixo_x": pergunta.get("eixo_x"),
                    "eixo_y": pergunta.get("eixo_y", []),
                    "linhas": linhas,
                    "ate_o_mes": ate_o_mes,
                }
            )
    return graficos


def gravar(conexao: psycopg.Connection, publicacao: Publicacao) -> dict[str, int]:
    """Apaga e reescreve as cinco tabelas numa transação. Devolve as linhas por tabela.

    Recusa, antes de apagar qualquer coisa, uma publicação vazia: a Gold ou a `serie` sem dado
    (clone novo antes do `analitico_job`) deixariam o site em branco com uma execução "de sucesso".
    """
    _conferir_nao_vazia(publicacao)
    with conexao.transaction():
        for tabela in _TABELAS:
            conexao.execute(f"delete from {tabela}")  # noqa: S608 (nome fixo, não vem de fora)
        _inserir(conexao, "previsao_subitem", publicacao.previsao)
        _inserir(conexao, "subitem", publicacao.subitem)
        _inserir(conexao, "uf_praca", publicacao.uf_praca)
        _inserir(conexao, "resumo_subitem", publicacao.resumo)
        with conexao.cursor() as cursor:
            cursor.executemany(
                "insert into painel_grafico"
                " (id, titulo, grafico, eixo_x, eixo_y, linhas, ate_o_mes)"
                " values (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        g["id"],
                        g["titulo"],
                        g["grafico"],
                        g["eixo_x"],
                        json.dumps(g["eixo_y"]),
                        None if g["linhas"] is None else json.dumps(g["linhas"]),
                        g["ate_o_mes"],
                    )
                    for g in publicacao.painel
                ],
            )
        return {
            tabela: conexao.execute(f"select count(*) from {tabela}").fetchone()[0]  # noqa: S608
            for tabela in _TABELAS
        }


def _conferir_nao_vazia(publicacao: Publicacao) -> None:
    vazias = [
        nome
        for nome, dados in (
            ("previsao_subitem", publicacao.previsao),
            ("subitem", publicacao.subitem),
            ("resumo_subitem", publicacao.resumo),
        )
        if dados.empty
    ]
    vazias += [f"painel_grafico/{g['id']}" for g in publicacao.painel if g["linhas"] == []]
    if not publicacao.painel:
        vazias.append("painel_grafico")
    if vazias:
        raise ValueError(
            f"publicação recusada, tabelas vazias: {', '.join(vazias)}."
            " Rode o analitico_job e `just previsao` antes de publicar"
        )


def _inserir(conexao: psycopg.Connection, tabela: str, dados: pd.DataFrame) -> None:
    colunas = list(dados.columns)
    linhas = [
        tuple(None if pd.isna(v) else (v.to_pydatetime() if hasattr(v, "to_pydatetime") else v)
              for v in linha)
        for linha in dados.itertuples(index=False, name=None)
    ]  # fmt: skip
    marcadores = ", ".join(["%s"] * len(colunas))
    with conexao.cursor() as cursor:
        cursor.executemany(
            f"insert into {tabela} ({', '.join(colunas)}) values ({marcadores})",  # noqa: S608
            linhas,
        )


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--duckdb", type=Path, default=DUCKDB_PADRAO)
    parser.add_argument("--dsn-local", default=None, help="Postgres local; padrão: .env")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    destino = os.environ.get(VARIAVEL_DSN, "").strip()
    if not destino:
        logger.error(
            "%s vazio: preencha no .env a URL de Postgres do projeto do Supabase"
            " (Project Settings > Database > Connection string)",
            VARIAVEL_DSN,
        )
        return 2
    try:
        publicacao = coletar(args.duckdb, args.dsn_local or dsn_do_ambiente())
        # Sem comando preparado: o Transaction pooler do Supabase (porta 6543) troca de backend a
        # cada transação, e o comando preparado da execução anterior colidiria com o desta.
        with psycopg.connect(destino, connect_timeout=10, prepare_threshold=None) as conexao:
            contagem = gravar(conexao, publicacao)
    except (duckdb.Error, psycopg.Error, OSError, ValueError) as erro:
        logger.error("publicação interrompida: %s", erro)
        return 1
    for tabela, linhas in contagem.items():
        logger.info("%s: %d linhas", tabela, linhas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
