"""Monta, a partir da `serie` do Postgres local, o dashboard de uma praça para o site.

O site não lê o ambiente local: `publicar_site` roda esta função para cada praça, com o
histórico inteiro (`periodo=0`), e grava o resultado em `dashboard_localidade` no Supabase. O
backend só recorta o período pedido.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row


def load_dashboard_data(
    connection: psycopg.Connection, localidade: int = 1, periodo: int = 60
) -> dict[str, object]:
    filtros = {"localidade": localidade, "periodo": periodo}
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")

        cursor.execute(
            """
            with ultimo_mes as (
                select max(mes_referencia) as mes
                from serie.fct_inflacao_mensal
                where indice = 'IPCA' and codigo_localidade = 1 and nivel_categoria = 'geral'
            )
            select u.mes,
                max(f.variacao_acum_12m_pct) filter (where f.indice = 'IPCA') as ipca_12m_pct,
                max(f.variacao_acum_12m_pct) filter (where f.indice = 'INPC') as inpc_12m_pct
            from ultimo_mes u
            left join serie.fct_inflacao_mensal f
                on f.mes_referencia = u.mes
                and f.codigo_localidade = %(localidade)s
                and f.nivel_categoria = 'geral'
            group by u.mes
            """,
            filtros,
        )
        summary = cursor.fetchone() or {}

        cursor.execute(
            """
            with ultimo_mes as (
                select max(mes_referencia) as mes
                from serie.fct_inflacao_mensal
                where indice = 'IPCA' and codigo_localidade = 1 and nivel_categoria = 'geral'
            )
            select c.nome_categoria as setor,
                round(f.variacao_acum_12m_pct, 2) as inflacao_12m_pct,
                to_char(f.mes_referencia, 'MM/YYYY') as ate_o_mes
            from serie.fct_inflacao_mensal f
            join ultimo_mes u on f.mes_referencia = u.mes
            join serie.dim_cesta_ipca_scd2 c on c.id_versao_cesta = f.id_versao_cesta
            where f.indice = 'IPCA'
                and f.codigo_localidade = %(localidade)s
                and f.nivel_categoria in ('geral', 'grupo')
            order by f.nivel_categoria = 'geral' desc, f.variacao_acum_12m_pct desc
            """,
            filtros,
        )
        sectors = cursor.fetchall()

        cursor.execute(
            """
            with ultimo_mes as (
                select max(mes_referencia) as mes
                from serie.fct_inflacao_mensal
                where indice = 'IPCA' and codigo_localidade = 1 and nivel_categoria = 'geral'
            )
            select l.nome_localidade as localidade, l.uf,
                max(f.variacao_acum_12m_pct) filter (where f.indice = 'IPCA') as ipca_12m_pct,
                max(f.variacao_acum_12m_pct) filter (where f.indice = 'INPC') as inpc_12m_pct
            from serie.fct_inflacao_mensal f
            join ultimo_mes u on f.mes_referencia = u.mes
            join serie.dim_localidade l on l.codigo_localidade = f.codigo_localidade
            where f.nivel_categoria = 'geral'
            group by l.codigo_localidade, l.nome_localidade, l.uf
            order by l.codigo_localidade = 1 desc, ipca_12m_pct desc nulls last
            """
        )
        locations = cursor.fetchall()

        cursor.execute(
            """
            select codigo_localidade, nome_localidade, uf
            from serie.dim_localidade
            order by codigo_localidade = 1 desc, nome_localidade
            """
        )
        location_options = cursor.fetchall()

        cursor.execute(
            """
            with ultimo_mes as (
                select max(mes_referencia) as mes
                from serie.fct_inflacao_mensal
                where indice = 'IPCA' and codigo_localidade = 1 and nivel_categoria = 'geral'
            )
            select f.mes_referencia,
                max(f.variacao_acum_12m_pct) filter (where f.indice = 'IPCA') as ipca_12m_pct,
                max(f.variacao_acum_12m_pct) filter (where f.indice = 'INPC') as inpc_12m_pct
            from serie.fct_inflacao_mensal f
            cross join ultimo_mes u
            where f.codigo_localidade = %(localidade)s
                and f.nivel_categoria = 'geral'
                and (%(periodo)s = 0
                    or f.mes_referencia > u.mes - make_interval(months => %(periodo)s))
            group by f.mes_referencia
            order by f.mes_referencia
            """,
            filtros,
        )
        history = cursor.fetchall()

        cursor.execute(
            """
            select extract(month from f.mes_referencia)::int as mes_numero,
                (array['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out',
                    'nov', 'dez'])[extract(month from f.mes_referencia)::int] as mes,
                round(avg(f.variacao_mensal_pct) filter (where f.nivel_categoria = 'geral'), 2)
                    as indice_geral_pct,
                round(avg(f.variacao_mensal_pct) filter (where f.codigo_categoria = '1'), 2)
                    as alimentacao_pct,
                round(avg(f.variacao_mensal_pct) filter (where f.codigo_categoria = '2'), 2)
                    as habitacao_pct,
                round(avg(f.variacao_mensal_pct) filter (where f.codigo_categoria = '4'), 2)
                    as vestuario_pct,
                round(avg(f.variacao_mensal_pct) filter (where f.codigo_categoria = '5'), 2)
                    as transportes_pct
            from serie.fct_inflacao_mensal f
            where f.indice = 'IPCA'
                and f.codigo_localidade = %(localidade)s
                and f.nivel_categoria in ('geral', 'grupo')
                and f.mes_referencia >= date '2006-07-01'
            group by mes_numero
            order by mes_numero
            """,
            filtros,
        )
        seasonality = cursor.fetchall()

        cursor.execute(
            """
            with base as (
                select numero_indice
                from serie.fct_inflacao_mensal
                where indice = 'IPCA'
                    and codigo_localidade = %(localidade)s
                    and nivel_categoria = 'geral'
                    and mes_referencia = date '2006-01-01'
            )
            select f.mes_referencia,
                round(100 * b.numero_indice / f.numero_indice, 2) as poder_compra_100_reais
            from serie.fct_inflacao_mensal f
            cross join base b
            where f.indice = 'IPCA'
                and f.codigo_localidade = %(localidade)s
                and f.nivel_categoria = 'geral'
                and f.numero_indice is not null
                and f.mes_referencia >= date '2006-01-01'
            order by f.mes_referencia
            """,
            filtros,
        )
        purchasing_power = cursor.fetchall()

    return {
        "latest_month": summary.get("mes"),
        "kpis": {
            "ipca_12m_pct": summary.get("ipca_12m_pct"),
            "inpc_12m_pct": summary.get("inpc_12m_pct"),
        },
        "sectors": sectors,
        "locations": locations,
        "location_options": location_options,
        "history": history,
        "seasonality": seasonality,
        "purchasing_power": purchasing_power,
    }
