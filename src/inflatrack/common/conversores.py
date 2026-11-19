"""Valores e datas em formato brasileiro, como chegam em planilhas de preço.

Vindos do PR #21 (Cesta Básica PROCON, de Artur Fernandes Galdino), com `Decimal` no lugar de
`float`: dinheiro vira centavos inteiros sem erro de arredondamento.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

FORMATOS_DATA = ("%Y-%m-%d", "%d/%m/%Y")


def converter_centavos(valor: str) -> int:
    """`R$ 1.234,56` -> 123456. Recusa vazio, negativo e mais de duas casas decimais."""
    texto = str(valor).strip().replace("R$", "").replace(" ", "")
    if "," in texto:
        # Com vírgula decimal, o ponto só pode ser separador de milhar.
        texto = texto.replace(".", "").replace(",", ".")
    try:
        numero = Decimal(texto)
    except InvalidOperation as erro:
        raise ValueError(f"valor inválido: {valor!r}") from erro
    if not numero.is_finite() or numero < 0:
        raise ValueError(f"valor inválido: {valor!r}")
    centavos = numero * 100
    if centavos != centavos.to_integral_value():
        raise ValueError(f"valor com mais de duas casas decimais: {valor!r}")
    return int(centavos)


def converter_data(valor: str) -> date:
    """`2026-11-19` ou `19/11/2026` -> date(2026, 11, 19)."""
    texto = str(valor).strip()
    for formato in FORMATOS_DATA:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {valor!r}")
