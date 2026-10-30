"""Partições dos ativos e a regra que liga cada mês ao agregado do SIDRA.

Só o IPCA/INPC (por mês) e o PIB (por ano) são particionados, porque nos dois a coleta já é
uma requisição por período: a partição não custa chamada a mais e permite reprocessar um
período passado (*backfill*). As demais fontes baixam a série inteira por chamada, e
partição ali só multiplicaria chamadas de API.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from dagster import MonthlyPartitionsDefinition, TimeWindowPartitionsDefinition

# O IPCA trocou de agregado no SIDRA duas vezes; a partição mensal esconde isso.
IPCA_MENSAL = MonthlyPartitionsDefinition(start_date="2006-07-01")
INPC_MENSAL = MonthlyPartitionsDefinition(start_date="2020-01-01")
IPCA_INDICE_MENSAL = MonthlyPartitionsDefinition(start_date="1979-12-01")

# PIB (SIDRA 1846): o ingestor faz uma requisição por ano (`--de`/`--ate`), e a série começa
# em 1996. `end_offset=1` inclui o ano corrente, ainda incompleto (o 1T sai em junho).
PIB_ANUAL = TimeWindowPartitionsDefinition(
    cron_schedule="0 0 1 1 *", start="1996", fmt="%Y", end_offset=1
)

# Cada divulgação do IBGE revisa trimestres anteriores, inclusive do ano passado: o
# agendamento relê o ano corrente e o anterior. A Bronze só acrescenta o que mudou.
ANOS_RELIDOS_PIB = 1

# (primeiro mês, último mês, agregado) — mesma divisão da receita `just seed`.
VIGENCIA_AGREGADOS_IPCA = (
    (date(2006, 7, 1), date(2011, 12, 1), 2938),
    (date(2012, 1, 1), date(2019, 12, 1), 1419),
    (date(2020, 1, 1), date.max, 7060),
)


# Política de dado atrasado do IPCA/INPC: o IBGE pode republicar um mês já divulgado, e
# a API não tem como pedir "só o que mudou". Reler os meses recentes é o único jeito de
# ver uma revisão; a Bronze só acrescenta, então reler um mês sem revisão não grava nada.
MESES_RELIDOS = 3


def janela_de_releitura(execucao: date) -> tuple[str, list[str]]:
    """Chaves de partição pedidas numa execução do agendamento do SIDRA.

    Devolve o mês novo (o anterior ao da execução, que o IBGE divulga agora) e os
    ``MESES_RELIDOS`` meses antes dele, do mais recente para o mais antigo.
    """
    ano, mes = execucao.year, execucao.month
    chaves = []
    for _ in range(MESES_RELIDOS + 1):
        ano, mes = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
        chaves.append(date(ano, mes, 1).isoformat())
    return chaves[0], chaves[1:]


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
