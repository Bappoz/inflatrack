"""Cliente e extrator da série de Salário Mínimo Nominal e Necessário do DIEESE.

Acessa a página pública da Pesquisa Nacional da Cesta Básica de Alimentos,
extrai a tabela histórica (desde julho de 1994) e normaliza os indicadores.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger("inflatrack.dieese")

DIEESE_URL = "https://www.dieese.org.br/analisecestabasica/salarioMinimo.html"

MAPA_MESES: dict[str, int] = {
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


class DieeseError(ValueError):
    """Erro ao baixar ou processar a página do DIEESE."""


def baixar_html(cliente: httpx.Client | None = None, url: str = DIEESE_URL) -> str:
    """Faz a requisição HTTP GET para a página de salário mínimo do DIEESE."""
    headers = {"User-Agent": "InflaTrack/1.0 (Data Engineering Pipeline)"}
    if cliente is not None:
        resposta = cliente.get(url, headers=headers, timeout=30.0)
        resposta.raise_for_status()
        # O site do DIEESE utiliza codificação ISO-8859-1 (latin1)
        conteudo = (
            resposta.content.decode("latin1")
            if "iso-8859-1" in resposta.headers.get("content-type", "").lower()
            else resposta.text
        )
        return conteudo

    with httpx.Client() as client:
        resposta = client.get(url, headers=headers, timeout=30.0)
        resposta.raise_for_status()
        conteudo = (
            resposta.content.decode("latin1")
            if "iso-8859-1" in resposta.headers.get("content-type", "").lower()
            else resposta.text
        )
        return conteudo


def _limpar_moeda(valor_str: str) -> float | None:
    """Converte 'R$ 1.621,00' para float 1621.0."""
    texto_limpo = re.sub(r"[^\d,]", "", valor_str).replace(",", ".")
    if not texto_limpo:
        return None
    try:
        return float(texto_limpo)
    except ValueError:
        return None


def extrair_tabela(html_content: str) -> pd.DataFrame:
    """Extrai as linhas de meses da tabela HTML e estrutura em DataFrame Pandas."""
    match_tabela = re.search(r"<table[^>]*>(.*?)</table>", html_content, re.DOTALL | re.IGNORECASE)
    if not match_tabela:
        raise DieeseError("Nenhuma tabela encontrada no conteúdo HTML fornecido.")

    conteudo_tabela = match_tabela.group(1)
    linhas = re.findall(r"<tr([^>]*)>(.*?)</tr>", conteudo_tabela, re.DOTALL | re.IGNORECASE)
    if not linhas:
        raise DieeseError("A tabela HTML não contém linhas <tr>.")

    registros: list[dict[str, Any]] = []
    ano_vigente: int | None = None

    for attrs, linha in linhas:
        # Detecta cabeçalhos intermediários com o ano
        # Ex: <tr class="subtitulo"><td colspan="3">2026</td></tr>
        if "subtitulo" in attrs.lower():
            match_ano = re.search(r"(\d{4})", linha)
            if match_ano:
                ano_vigente = int(match_ano.group(1))
            continue

        colunas = re.findall(r"<td[^>]*>(.*?)</td>", linha, re.DOTALL | re.IGNORECASE)
        if len(colunas) < 3:
            # Pode ser uma linha com apenas o ano em <td>2026</td>
            if len(colunas) == 1:
                match_ano = re.search(r"^\s*(\d{4})\s*$", re.sub(r"<.*?>", "", colunas[0]))
                if match_ano:
                    ano_vigente = int(match_ano.group(1))
            continue
        if ano_vigente is None:
            continue

        mes_texto = html.unescape(re.sub(r"<.*?>", "", colunas[0])).strip().lower()
        if mes_texto not in MAPA_MESES:
            continue

        mes_num = MAPA_MESES[mes_texto]
        salario_nom = _limpar_moeda(colunas[1])
        salario_nec = _limpar_moeda(colunas[2])

        if salario_nom is None or salario_nec is None or salario_nom <= 0:
            continue

        multiplo = round(salario_nec / salario_nom, 4)
        ano_mes = f"{ano_vigente:04d}-{mes_num:02d}"
        data_ref = f"{ano_mes}-01"

        registros.append(
            {
                "ano_mes": ano_mes,
                "data_referencia": data_ref,
                "ano": ano_vigente,
                "mes": mes_num,
                "salario_nominal": salario_nom,
                "salario_necessario": salario_nec,
                "multiplo_necessario_nominal": multiplo,
            }
        )

    if not registros:
        raise DieeseError("Nenhum registro válido de salário mínimo pôde ser extraído da tabela.")

    df = pd.DataFrame(registros)
    df = df.sort_values(by="data_referencia").reset_index(drop=True)
    df["data_referencia"] = pd.to_datetime(df["data_referencia"]).dt.date
    return df
