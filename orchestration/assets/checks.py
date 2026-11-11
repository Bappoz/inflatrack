"""Asset checks de frescura (SLA) e volume, um por fonte e um para a Gold de consumo.

Atende ao requisito da Entrega 3: métrica de freshness e SLA declarado. Cada fonte tem um
`Sla` (tabela, coluna da data de referência, atraso máximo em dias corridos e volume mínimo) e
um check que lê o DuckDB em só leitura e compara a data mais recente da tabela com hoje.

Todo check abre o DuckDB, então entra no pool `duckdb_writer` (PLAN_E3_E4.md, Seção 6.3):
uma conexão aberta, mesmo só leitura, trava o dbt e os loaders.

Severidade: volume abaixo do mínimo ou tabela ausente é ERROR; só atraso além do SLA é WARN.
O SLA de cada fonte vem da cadência de divulgação dela (docs/evidencias/e3/sla_e_freshness.md).
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
from dagster import (
    AssetCheckExecutionContext,
    AssetCheckResult,
    AssetCheckSeverity,
    AssetKey,
    asset_check,
)

from orchestration.assets.clima import clima_duckdb, clima_medicoes_duckdb, clima_provisorio_duckdb
from orchestration.assets.commodities import commodities_duckdb
from orchestration.assets.comum import POOL_DUCKDB
from orchestration.assets.dolar import dolar_duckdb
from orchestration.assets.pib_internacional import pib_internacional_duckdb
from orchestration.assets.salario_minimo import salario_minimo_duckdb
from orchestration.assets.selic import selic_duckdb

DB_PADRAO = Path("data/duckdb/inflatrack.duckdb")


@dataclass(frozen=True)
class Sla:
    """Contrato de frescura de uma tabela."""

    tabela: str
    # Expressão SQL que dá a data de referência de cada linha (ex.: `data_referencia`).
    data: str
    atraso_max_dias: int
    sla_declarado: str
    volume_minimo: int
    rotulo: str
    unidade: str = "linhas"


SLA_DOLAR = Sla(
    "bronze.dolar_boletim",
    "data_referencia",
    5,
    "D-1 útil (máximo 5 dias corridos)",
    100,
    "Dólar",
)
SLA_SELIC = Sla(
    "bronze.selic_taxa",
    "data_referencia",
    5,
    "D+1 útil no SGS (máximo 5 dias corridos)",
    100,
    "Selic",
)
SLA_MACRO = Sla(
    "gold.fct_macroeconomia_mensal",
    "mes_referencia",
    45,
    "Mensal (máximo 45 dias após início do mês)",
    12,
    "Macroeconomia",
    "meses",
)
# O IBGE divulga o IPCA de um mês por volta do dia 10 do mês seguinte: antes disso o último mês
# começou há até ~70 dias. 75 cobre o pior caso sem alarme falso.
SLA_IPCA = Sla(
    "bronze.ipca_observacao",
    "mes_referencia",
    75,
    "Mensal, divulgado ~10 dias após o fim do mês (máximo 75 dias após o início do mês)",
    1_000_000,
    "IPCA/INPC",
)
# O DIEESE atualiza a tabela no começo do mês seguinte; mesma folga do IPCA.
SLA_SALARIO_MINIMO = Sla(
    "bronze.salario_minimo_mes",
    "data_referencia",
    75,
    "Mensal (máximo 75 dias após o início do mês)",
    387,  # meses desde jul/1994 na checagem da Bronze (VOLUME_MINIMO_REFERENCIA)
    "Salário mínimo",
    "meses",
)
# data_referencia é o 1º dia do trimestre. O IBGE divulga o trimestre cerca de 2 meses depois
# de ele acabar: antes disso o último trimestre começou há ~247 dias. 260 dá folga.
SLA_PIB = Sla(
    "bronze.pib_valor",
    "data_referencia",
    260,
    "Trimestral, divulgado ~2 meses após o trimestre (máximo 260 dias após o início dele)",
    920,  # ao menos 10 anos x 4 trimestres x 23 categorias
    "PIB",
)
# O Banco Mundial só tem o ano fechado: a data de referência é 31/12. O ano Y costuma sair no
# 2º semestre de Y+1, então o ano mais recente pode ter até 2 anos de defasagem.
SLA_PIB_INTERNACIONAL = Sla(
    "bronze.pib_internacional_indicador",
    "make_date(ano, 12, 31)",
    730,
    "Anual (máximo 730 dias após o fim do ano de referência)",
    100,
    "PIB internacional",
)
# O catálogo de estações é coletado todo dia (clima_job); o que se mede é a coleta, não uma data
# do dado. O mínimo vem do volume de referência da Bronze (671 estações, -10%).
SLA_CLIMA_ESTACOES = Sla(
    "bronze.clima_estacao",
    "cast(_ingerido_em as date)",
    7,
    "Catálogo coletado todo dia (máximo 7 dias desde a última coleta)",
    604,
    "Catálogo de estações do INMET",
    "estações",
)
# Medições: o INMET republica o pacote BDMEP do ano corrente cerca de 1×/mês, com o mês anterior
# fechado. Antes da republicação o último dia publicado tem até ~40 dias; 60 dá folga. O mínimo
# equivale a ~10 anos de 14 estações (a carga desde 2006 traz mais de 100 mil leituras).
SLA_CLIMA_MEDICOES = Sla(
    "bronze.clima_medicao",
    "data_referencia",
    60,
    "Pacote BDMEP republicado ~1×/mês (máximo 60 dias desde o último dia medido)",
    50_000,
    "Medições diárias do INMET (BDMEP)",
    "leituras",
)
# Provisório (Open-Meteo): a coleta diária vai até ontem; 5 dias cobrem um fim de semana sem
# coleta e o atraso da reanálise. O mínimo é um dia das estações do de-para.
SLA_CLIMA_PROVISORIO = Sla(
    "bronze.clima_medicao_provisoria",
    "data_referencia",
    5,
    "Coleta diária até ontem (máximo 5 dias desde o último dia coberto)",
    16,
    "Clima provisório (Open-Meteo)",
    "leituras",
)

# Commodities misturam séries diárias e mensais (`intervalo`); o SLA vale por intervalo.
ATRASO_MAX_COMMODITIES = {"daily": 7, "monthly": 75}
VOLUME_MINIMO_COMMODITIES = 100


def _resposta(passou: bool, volume_ok: bool, descricao: str, metadata: dict) -> AssetCheckResult:
    return AssetCheckResult(
        passed=passou,
        severity=AssetCheckSeverity.WARN if volume_ok else AssetCheckSeverity.ERROR,
        metadata=metadata,
        description=descricao,
    )


def _erro(descricao: str) -> AssetCheckResult:
    return AssetCheckResult(passed=False, severity=AssetCheckSeverity.ERROR, description=descricao)


def _consultar(sql: str) -> list[tuple] | AssetCheckResult:
    """Roda a consulta em só leitura; devolve o resultado do check se não der para consultar."""
    if not DB_PADRAO.exists():
        return _erro(f"Banco de dados DuckDB não encontrado em {DB_PADRAO}")
    con = duckdb.connect(str(DB_PADRAO), read_only=True)
    try:
        return con.execute(sql).fetchall()
    except duckdb.CatalogException as erro:
        return _erro(f"Tabela ausente no DuckDB (a carga ainda não rodou?): {erro}")
    finally:
        con.close()


def avaliar(sla: Sla) -> AssetCheckResult:
    """Compara a data mais recente de `sla.tabela` com hoje e confere o volume mínimo."""
    linhas = _consultar(f"select max({sla.data}), count(*) from {sla.tabela}")
    if isinstance(linhas, AssetCheckResult):
        return linhas
    mais_recente, total = linhas[0]
    if mais_recente is None:
        return _erro(f"Tabela {sla.tabela} está vazia")

    mais_recente = mais_recente if isinstance(mais_recente, date) else mais_recente.date()
    atraso = (date.today() - mais_recente).days
    cumpre_sla = atraso <= sla.atraso_max_dias
    cumpre_volume = total >= sla.volume_minimo
    status = "CUMPRIDO" if cumpre_sla else "ALERTA DE DESATUALIZAÇÃO"
    return _resposta(
        cumpre_sla and cumpre_volume,
        cumpre_volume,
        f"{sla.rotulo} até {mais_recente} ({atraso}d de defasagem, {total} {sla.unidade}). "
        f"SLA: {status}.",
        {
            "sla_declarado": sla.sla_declarado,
            "data_mais_recente": str(mais_recente),
            "dias_atraso": atraso,
            "atraso_maximo_dias": sla.atraso_max_dias,
            "total_linhas": total,
            "volume_minimo_esperado": sla.volume_minimo,
        },
    )


def avaliar_commodities() -> AssetCheckResult:
    """Cada commodity precisa estar em dia para o intervalo dela (diário ou mensal)."""
    linhas = _consultar(
        "select symbol, intervalo, max(data_referencia), count(*) "
        "from bronze.commodities_cotacao group by 1, 2 order by 1"
    )
    if isinstance(linhas, AssetCheckResult):
        return linhas
    if not linhas:
        return _erro("Tabela bronze.commodities_cotacao está vazia")

    hoje = date.today()
    total = sum(linha[3] for linha in linhas)
    atrasadas = {}
    for simbolo, intervalo, mais_recente, _ in linhas:
        atraso = (hoje - mais_recente).days
        if atraso > ATRASO_MAX_COMMODITIES.get(intervalo, ATRASO_MAX_COMMODITIES["daily"]):
            atrasadas[simbolo] = f"{mais_recente} ({atraso}d, {intervalo})"

    cumpre_volume = total >= VOLUME_MINIMO_COMMODITIES
    status = "CUMPRIDO" if not atrasadas else "ALERTA DE DESATUALIZAÇÃO"
    return _resposta(
        not atrasadas and cumpre_volume,
        cumpre_volume,
        f"Commodities: {len(linhas) - len(atrasadas)} de {len(linhas)} séries em dia, "
        f"{total} linhas. SLA: {status}.",
        {
            "sla_declarado": "Diária: máximo 7 dias; mensal: máximo 75 dias após o início do mês",
            "series": len(linhas),
            "series_atrasadas": ", ".join(f"{s}: {d}" for s, d in atrasadas.items()) or "nenhuma",
            "total_linhas": total,
            "volume_minimo_esperado": VOLUME_MINIMO_COMMODITIES,
        },
    )


def _check_de(nome: str, ativo, sla: Sla, descricao: str):
    @asset_check(name=nome, asset=ativo, pool=POOL_DUCKDB, description=descricao)
    def _check(context: AssetCheckExecutionContext) -> AssetCheckResult:
        return avaliar(sla)

    return _check


check_dolar_freshness_e_volume = _check_de(
    "check_dolar_freshness_e_volume",
    dolar_duckdb,
    SLA_DOLAR,
    "SLA de atualização e volume mínimo para cotações do Dólar comercial PTAX.",
)
check_selic_freshness_e_volume = _check_de(
    "check_selic_freshness_e_volume",
    selic_duckdb,
    SLA_SELIC,
    "SLA de atualização e volume mínimo para taxas Selic diárias.",
)
check_macroeconomia_mensal_freshness = _check_de(
    "check_macroeconomia_mensal_freshness",
    AssetKey(["gold", "fct_macroeconomia_mensal"]),
    SLA_MACRO,
    "SLA da tabela de consumo gold.fct_macroeconomia_mensal (câmbio x juros).",
)
check_ipca_freshness_e_volume = _check_de(
    "check_ipca_freshness_e_volume",
    AssetKey("ipca_duckdb"),
    SLA_IPCA,
    "SLA de divulgação e volume mínimo das observações de IPCA/INPC.",
)
check_salario_minimo_freshness_e_volume = _check_de(
    "check_salario_minimo_freshness_e_volume",
    salario_minimo_duckdb,
    SLA_SALARIO_MINIMO,
    "SLA de atualização e volume mínimo do salário mínimo do DIEESE.",
)
check_pib_freshness_e_volume = _check_de(
    "check_pib_freshness_e_volume",
    AssetKey("pib_duckdb"),
    SLA_PIB,
    "SLA de divulgação trimestral e volume mínimo do PIB e setores (SIDRA 1846).",
)
check_pib_internacional_freshness_e_volume = _check_de(
    "check_pib_internacional_freshness_e_volume",
    pib_internacional_duckdb,
    SLA_PIB_INTERNACIONAL,
    "SLA anual e volume mínimo do PIB de China, EUA e Rússia (Banco Mundial).",
)
check_clima_estacoes_freshness_e_volume = _check_de(
    "check_clima_estacoes_freshness_e_volume",
    clima_duckdb,
    SLA_CLIMA_ESTACOES,
    "Coleta diária e volume mínimo do catálogo de estações do INMET.",
)
check_clima_medicoes_freshness_e_volume = _check_de(
    "check_clima_medicoes_freshness_e_volume",
    clima_medicoes_duckdb,
    SLA_CLIMA_MEDICOES,
    "Defasagem do último dia medido e volume mínimo das medições diárias do INMET (BDMEP).",
)
check_clima_provisorio_freshness_e_volume = _check_de(
    "check_clima_provisorio_freshness_e_volume",
    clima_provisorio_duckdb,
    SLA_CLIMA_PROVISORIO,
    "Clima provisório (Open-Meteo) coberto até poucos dias atrás, enquanto o INMET não publica.",
)


@asset_check(
    name="check_commodities_freshness_e_volume",
    asset=commodities_duckdb,
    pool=POOL_DUCKDB,
    description="SLA por série (diária ou mensal) e volume mínimo das commodities (Alpha Vantage).",
)
def check_commodities_freshness_e_volume(
    context: AssetCheckExecutionContext,
) -> AssetCheckResult:
    return avaliar_commodities()
