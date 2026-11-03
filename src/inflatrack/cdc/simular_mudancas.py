"""Demonstração do CDC: mudanças de verdade no Postgres, reprocessamento e evento atrasado.

Cria um lojista fictício (recriado a cada execução), altera, apaga e insere linhas e captura
entre um passo e outro, mostrando o que chegou à Bronze:

1. **Cadastro e foto inicial:** lojista, três produtos e vendas.
2. **Mudanças:** reajuste de preço, alteração de custo, renomeação e exclusão de produto.
3. **Reprocessamento:** a captura grava e "cai" antes de avançar o slot; a seguinte lê os mesmos
   eventos e nenhum duplica.
4. **Chegada atrasada:** um reajuste de janeiro é registrado depois do de março já capturado.
   A Bronze guarda na ordem em que soube; a Silver ordena por ``aplicado_em``, e o histórico de
   preços (``dim_produto_preco_scd2``) entra na ordem certa.

Ao fim, procura o CNPJ em todas as linhas da Bronze e falha se o encontrar.

Uso::

    uv run python -m inflatrack.cdc.simular_mudancas
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import duckdb
import psycopg
from deltalake import DeltaTable
from dotenv import load_dotenv

from inflatrack.cdc import transacional
from inflatrack.common import bronze
from inflatrack.common.db import dsn_do_ambiente

logger = logging.getLogger("inflatrack.simular_cdc")

CNPJ_FICTICIO = "11222333000181"
BRASILIA = 5300108
# Códigos reais da cesta. Numa base sem a carga do IPCA eles ainda não existem na referência.
CESTA = {"1": "grupo", "1101002": "subitem", "1111004": "subitem", "1104003": "subitem"}


def _preparar(conexao: psycopg.Connection) -> None:
    """Garante a referência e recomeça do zero. O DELETE em cascata também vira evento."""
    for codigo, nivel in CESTA.items():
        conexao.execute(
            "insert into classificacao (codigo, nivel) values (%s, %s)"
            " on conflict (codigo) do nothing",
            (codigo, nivel),
        )
    conexao.execute("delete from lojista where cnpj = %s", (CNPJ_FICTICIO,))


def _cadastrar(conexao: psycopg.Connection) -> dict[str, int]:
    (id_lojista,) = conexao.execute(
        "insert into lojista (nome_fantasia, cnpj, codigo_localidade, codigo_grupo_ipca, criado_em)"
        " values ('Mercadinho Demonstração', %s, %s, '1', '2025-09-01 12:00+00') returning id",
        (CNPJ_FICTICIO, BRASILIA),
    ).fetchone()
    produtos = {}
    for nome, preco, custo, subitem in (
        ("Arroz 5kg", 2500, 1800, "1101002"),
        ("Leite 1L", 550, 400, "1111004"),
        ("Feijão 1kg", 900, 650, "1104003"),
    ):
        (produtos[nome],) = conexao.execute(
            "insert into produto (id_lojista, nome, preco_inicial_centavos,"
            " custo_inicial_centavos, codigo_subitem_ipca, criado_em)"
            " values (%s, %s, %s, %s, %s, '2025-09-15 12:00+00') returning id",
            (id_lojista, nome, preco, custo, subitem),
        ).fetchone()
    for mes, quantidade, receita in (
        ("2025-10-01", 120, 300000),
        ("2025-11-01", 110, 275000),
        ("2026-04-01", 95, 251750),
    ):
        conexao.execute(
            "insert into venda_mensal (id_produto, mes_referencia, quantidade, receita_centavos)"
            " values (%s, %s, %s, %s)",
            (produtos["Arroz 5kg"], mes, quantidade, receita),
        )
    return produtos


def _mudar(conexao: psycopg.Connection, produtos: dict[str, int]) -> None:
    arroz, leite, feijao = produtos["Arroz 5kg"], produtos["Leite 1L"], produtos["Feijão 1kg"]
    conexao.execute(
        "insert into reajuste_custo (id_produto, custo_anterior_centavos, custo_novo_centavos,"
        " motivo, aplicado_em) values (%s, 1800, 1900, 'novo fornecedor', '2026-02-20 12:00+00')",
        (arroz,),
    )
    conexao.execute(
        "insert into reajuste (id_produto, preco_anterior_centavos, preco_novo_centavos,"
        " motivo, aplicado_em) values (%s, 2500, 2650, 'repasse do IPCA', '2026-03-10 12:00+00')",
        (arroz,),
    )
    conexao.execute("update produto set nome = 'Leite Integral 1L' where id = %s", (leite,))
    conexao.execute("delete from produto where id = %s", (feijao,))


def _registrar_atrasado(conexao: psycopg.Connection, arroz: int) -> None:
    conexao.execute(
        "insert into reajuste (id_produto, preco_anterior_centavos, preco_novo_centavos,"
        " motivo, aplicado_em) values (%s, 2500, 2580, 'lançado com atraso',"
        " '2026-01-05 12:00+00')",
        (arroz,),
    )


def _bronze_tem_cnpj(destino: Path) -> bool:
    # Pelo DuckDB, e não por to_pyarrow_table: com deltalake 1.6.6 e pyarrow 25.0.1, um processo que
    # só lê o Delta pelo Arrow aborta ao terminar (código 134), mesmo depois de ter dado certo.
    mudanca = DeltaTable(bronze.caminho(destino, transacional.TABELA_DELTA)).to_pyarrow_dataset()
    with duckdb.connect() as conexao:
        conexao.register("mudanca", mudanca)
        (encontradas,) = conexao.execute(
            "select count(*) from mudanca"
            " where contains(coalesce(antes, '') || coalesce(depois, ''), ?)",
            [CNPJ_FICTICIO],
        ).fetchone()
    return encontradas > 0


def simular(conexao: psycopg.Connection, destino: Path, chave: str, slot: str) -> dict[str, object]:
    """Roda o cenário e devolve o que cada captura leu e gravou. Conexão em ``autocommit``."""

    def captura(**opcoes) -> transacional.Captura:
        return transacional.capturar(conexao, destino, chave, slot=slot, **opcoes)

    captura()  # garante o slot antes do cenário, para os eventos abaixo serem CDC, não foto
    _preparar(conexao)
    produtos = _cadastrar(conexao)
    cadastro = captura()
    logger.info("1. cadastro: %d lidas, %d novas", cadastro.lidas, cadastro.novas)

    _mudar(conexao, produtos)
    mudancas = captura()
    logger.info("2. mudanças: %d lidas, %d novas", mudancas.lidas, mudancas.novas)

    conexao.execute(
        "update produto set preco_inicial_centavos = preco_inicial_centavos where id = %s",
        (produtos["Leite 1L"],),
    )
    antes_da_queda = captura(avancar=False)
    depois_da_queda = captura()
    logger.info(
        "3. reprocessamento: antes da queda %d/%d, depois %d/%d (lidas/novas)",
        antes_da_queda.lidas,
        antes_da_queda.novas,
        depois_da_queda.lidas,
        depois_da_queda.novas,
    )

    _registrar_atrasado(conexao, produtos["Arroz 5kg"])
    atrasado = captura()
    logger.info("4. chegada atrasada: %d lidas, %d novas", atrasado.lidas, atrasado.novas)

    if _bronze_tem_cnpj(destino):
        raise transacional.CdcError("o CNPJ chegou à Bronze: a remoção falhou")
    logger.info("5. LGPD: o CNPJ não aparece em nenhuma linha da Bronze")
    return {
        "produtos": produtos,
        "cadastro": cadastro,
        "mudancas": mudancas,
        "antes_da_queda": antes_da_queda,
        "depois_da_queda": depois_da_queda,
        "atrasado": atrasado,
    }


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dsn", default=None, help="padrão: montado do .env")
    parser.add_argument("--parquet-dir", default=transacional.DIRETORIO_PADRAO)
    parser.add_argument("--slot", default=transacional.SLOT_PADRAO)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        with psycopg.connect(
            args.dsn or dsn_do_ambiente(), autocommit=True, connect_timeout=5
        ) as conexao:
            simular(
                conexao,
                Path(args.parquet_dir),
                os.environ.get(transacional.VARIAVEL_CHAVE, ""),
                args.slot,
            )
    except (transacional.CdcError, psycopg.Error) as erro:
        logger.error("demonstração interrompida: %s", erro)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
