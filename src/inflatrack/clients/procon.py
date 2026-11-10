"""Cliente e extrator dos dados de Cesta Básica do PROCON.

Lê pesquisas de preços de itens essenciais coletados diretamente no varejo/atacado,
normalizando valores, unidades e mapeando com a cesta do IPCA.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from typing import Any

import httpx

logger = logging.getLogger("inflatrack.clients.procon")


class ProconError(ValueError):
    """Erro ao baixar ou processar dados da Cesta Básica do PROCON."""


COLUNAS_OBRIGATORIAS = {"data_pesquisa", "produto", "preco_medio", "praca"}


def _converter_valor(valor: Any) -> float | None:
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace("R$", "").replace(" ", "")
    if not texto:
        return None
    # Converte formato brasileiro 1.234,56 ou 12,50
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError as err:
        raise ProconError(f"Valor numérico inválido: {valor!r}") from err


def _converter_data(valor: Any) -> date:
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    formatos = ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"]
    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    raise ProconError(f"Formato de data inválido: {valor!r}")


def extrair_cesta_basica(conteudo_csv: str) -> list[dict[str, Any]]:
    """Extrai e normaliza linhas de um CSV de cesta básica do PROCON."""
    if not conteudo_csv or not conteudo_csv.strip():
        raise ProconError("Conteúdo CSV está vazio.")

    # Detecta delimitador (; ou ,)
    primeira_linha = conteudo_csv.strip().split("\n")[0]
    delimitador = ";" if ";" in primeira_linha else ","

    leitor = csv.DictReader(io.StringIO(conteudo_csv), delimiter=delimitador)
    if not leitor.fieldnames:
        raise ProconError("CSV sem cabeçalho.")

    campos_atuais = {campo.strip().lower() for campo in leitor.fieldnames if campo}
    faltantes = COLUNAS_OBRIGATORIAS - campos_atuais
    if faltantes:
        raise ProconError(f"Colunas obrigatórias ausentes no CSV: {faltantes}")

    registros: list[dict[str, Any]] = []
    for num_linha, linha in enumerate(leitor, start=2):
        # Normaliza chaves
        linha_norm = {k.strip().lower(): v.strip() if v else None for k, v in linha.items() if k}
        try:
            data_pesq = _converter_data(linha_norm["data_pesquisa"])
            preco_medio = _converter_valor(linha_norm["preco_medio"])
            if preco_medio is None:
                raise ProconError("preco_medio não pode ser nulo.")

            registro = {
                "data_pesquisa": data_pesq,
                "produto": linha_norm["produto"],
                "unidade": linha_norm.get("unidade") or "un",
                "preco_medio": preco_medio,
                "preco_minimo": _converter_valor(linha_norm.get("preco_minimo")),
                "preco_maximo": _converter_valor(linha_norm.get("preco_maximo")),
                "praca": linha_norm["praca"],
                "codigo_subitem_ipca": linha_norm.get("codigo_subitem_ipca"),
            }
            registros.append(registro)
        except Exception as err:
            raise ProconError(f"Erro na linha {num_linha}: {err}") from err

    if not registros:
        raise ProconError("Nenhum registro encontrado no CSV.")

    return registros


def baixar_cesta_basica(url: str, cliente: httpx.Client | None = None) -> str:
    """Faz a requisição HTTP GET para uma URL pública de CSV do PROCON."""
    headers = {"User-Agent": "InflaTrack/1.0 (Data Engineering Pipeline)"}
    if cliente is not None:
        resposta = cliente.get(url, headers=headers, timeout=30.0)
        resposta.raise_for_status()
        return resposta.text

    with httpx.Client() as client:
        resposta = client.get(url, headers=headers, timeout=30.0)
        resposta.raise_for_status()
        return resposta.text
