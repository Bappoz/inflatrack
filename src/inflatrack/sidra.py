"""Cliente da API de valores e metadados do SIDRA (IBGE).

Fatos medidos em 2026-09-08 que moldam este módulo:

* A API recusa requisições acima de 50.000 valores. Um mês do agregado 7060 são
  31.076 valores (17 localidades x 4 variáveis x 457 categorias) e passa; dois
  meses são 62.152 e devolvem HTTP 400. Daí a paginação obrigatória por mês.
* O modificador ``/f/c/h/n`` devolve só códigos, sem nomes e sem cabeçalho: o
  mesmo mês cai de 10,4 MB para 4,4 MB e de ~25 s para ~9 s. Os nomes vêm do
  endpoint de metadados, que é chamado uma vez por agregado.
* Valores ausentes chegam como ``...``, ``..``, ``-`` ou ``X``. ATENÇÃO: ``-``
  sozinho é ausente, mas ``-0.67`` é deflação de verdade. Filtrar por prefixo
  ``-`` apagaria todo mês de deflação sem erro nenhum.
* O separador decimal na API é PONTO (``-0.67``), diferente do .xlsx da
  interface web, que usa vírgula.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import date

import httpx

URL_VALORES = "https://apisidra.ibge.gov.br/values"
URL_METADADOS = "https://servicodados.ibge.gov.br/api/v3/agregados/{agregado}/metadados"

LIMITE_VALORES_POR_REQUISICAO = 50_000
MARCADORES_AUSENTE = frozenset({"...", "..", "-", "X"})
CODIGO_INDICE_GERAL = "7169"

_TIMEOUT = httpx.Timeout(120.0, connect=15.0)


class SidraError(RuntimeError):
    """Falha ao consultar o SIDRA que não vale a pena repetir."""


def meses(inicio: date, fim: date) -> Iterator[str]:
    """Gera períodos ``AAAAMM`` de `inicio` a `fim`, inclusive."""
    ano, mes = inicio.year, inicio.month
    while (ano, mes) <= (fim.year, fim.month):
        yield f"{ano}{mes:02d}"
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def eh_ausente(valor: str) -> bool:
    """True para marcador de ausência do SIDRA. Não confundir com valor negativo."""
    return valor in MARCADORES_AUSENTE


def buscar_valores(
    cliente: httpx.Client,
    agregado: int,
    periodo: str,
    *,
    niveis: str = "n1/all/n6/all/n7/all",
    classificacao: str | None = "315",
    tentativas: int = 4,
) -> list[dict[str, str]]:
    """Busca um período de um agregado no formato compacto (só códigos).

    Devolve a lista crua da API. A conversão fica em :mod:`inflatrack.ingest`
    para que a camada bruta possa ser gravada exatamente como veio.
    """
    partes = [URL_VALORES, "t", str(agregado), *niveis.split("/"), "v", "all", "p", periodo]
    if classificacao:
        partes += ["c" + classificacao, "all"]
    url = "/".join(partes) + "/f/c/h/n"

    ultimo_erro: Exception | None = None
    for tentativa in range(tentativas):
        try:
            resposta = cliente.get(url, timeout=_TIMEOUT)
            if resposta.status_code == 400:
                raise SidraError(f"{agregado}/{periodo}: {resposta.text.strip()[:200]}")
            resposta.raise_for_status()
            return resposta.json()
        except SidraError:
            raise
        except (httpx.HTTPError, ValueError) as erro:
            ultimo_erro = erro
            time.sleep(2**tentativa)
    raise SidraError(f"{agregado}/{periodo}: falhou em {tentativas} tentativas") from ultimo_erro


def buscar_metadados(cliente: httpx.Client, agregado: int) -> dict:
    """Metadados do agregado: variáveis, classificações e nomes das categorias."""
    resposta = cliente.get(URL_METADADOS.format(agregado=agregado), timeout=_TIMEOUT)
    resposta.raise_for_status()
    return resposta.json()


def categorias(metadados: dict) -> list[tuple[str, str, str, str | None]]:
    """Extrai ``(id_sidra, codigo, nome, codigo_pai)`` da classificação 315.

    O SIDRA entrega o rótulo colado, ``"1101002.Arroz"``. O código do pai é
    prefixo do filho: subitem 1101002 -> item 1101 -> subgrupo 11 -> grupo 1.
    O índice geral não tem ponto no rótulo e não tem pai.

    ``id_sidra`` é o identificador interno da categoria (campo ``id`` dos
    metadados) — é ele, e não o código natural, que os valores devolvem em
    ``D4C``. Os dois só coincidem por acaso no índice geral.
    """
    saida: list[tuple[str, str, str, str | None]] = []
    for classificacao in metadados.get("classificacoes", []):
        if str(classificacao.get("id")) != "315":
            continue
        for categoria in classificacao["categorias"]:
            id_sidra = str(categoria["id"])
            rotulo = categoria["nome"]
            codigo, separador, nome = rotulo.partition(".")
            if not separador:
                saida.append((id_sidra, CODIGO_INDICE_GERAL, rotulo.strip(), None))
                continue
            codigo = codigo.strip()
            pai = {7: codigo[:4], 4: codigo[:2], 2: codigo[:1]}.get(len(codigo))
            saida.append((id_sidra, codigo, nome.strip(), pai))
    return saida


def nivel_do_codigo(codigo: str) -> str:
    """Nível da cesta a partir do comprimento do código.

    ``7169`` é o sentinela do índice geral (sem estrutura de prefixo) —
    ver :func:`categorias`.
    """
    if codigo == CODIGO_INDICE_GERAL:
        return "geral"
    return {1: "grupo", 2: "subgrupo", 4: "item", 7: "subitem"}.get(len(codigo), "geral")
