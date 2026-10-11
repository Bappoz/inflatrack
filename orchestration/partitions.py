"""Partições dos ativos e a regra que liga cada mês ao agregado do SIDRA.

Só o IPCA/INPC é particionado: o código de ingestão das demais fontes já baixa a
janela inteira e faz *upsert*, então partição ali só multiplicaria chamadas de API.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from dagster import MonthlyPartitionsDefinition

# O IPCA trocou de agregado no SIDRA duas vezes; a partição mensal esconde isso.
IPCA_MENSAL = MonthlyPartitionsDefinition(start_date="2006-07-01")
INPC_MENSAL = MonthlyPartitionsDefinition(start_date="2020-01-01")
IPCA_INDICE_MENSAL = MonthlyPartitionsDefinition(start_date="1979-12-01")

# (primeiro mês, último mês, agregado) — mesma divisão da receita `just seed`.
VIGENCIA_AGREGADOS_IPCA = (
    (date(2006, 7, 1), date(2011, 12, 1), 2938),
    (date(2012, 1, 1), date(2019, 12, 1), 1419),
    (date(2020, 1, 1), date.max, 7060),
)


def mes_da_chave(chave: str) -> date:
    """Chave de partição do Dagster ('2026-07-01') para date."""
    return date.fromisoformat(chave)


def formato_sidra(mes: date) -> str:
    """date para o AAAA-MM aceito por `inflatrack.ingest`."""
    return mes.strftime("%Y-%m")


def segmentos_ipca(inicio: date, fim: date) -> Iterator[tuple[int, date, date]]:
    """Quebra [inicio, fim] em trechos de um único agregado do IPCA."""
    for primeiro, ultimo, agregado in VIGENCIA_AGREGADOS_IPCA:
        de, ate = max(inicio, primeiro), min(fim, ultimo)
        if de <= ate:
            yield agregado, de, ate
