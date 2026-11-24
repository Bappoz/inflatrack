{#
  Colunas de clima comuns às Gold mensais (fct_clima_mensal por praça, fct_clima_polo_mensal por
  polo agrícola). Espera um CTE com as colunas-base de um mês (temperatura, chuva, umidade, SPI,
  cobertura) e uma janela `w` ordenada por mês dentro da praça ou do polo, sobre a grade completa
  de meses: os lags são sempre "k meses antes", nunca "k linhas antes".
#}
{% macro colunas_clima_mensal(s='s') %}
    cast(round({{ s }}.dias_com_registro / {{ s }}.dias_no_mes, 4) as decimal(5, 4)) as cobertura_dias,

    -- temperatura (°C)
    cast({{ s }}.temp_media as decimal(8, 3)) as temp_media,
    cast({{ s }}.temp_min_absoluta as decimal(8, 3)) as temp_min_absoluta,
    cast({{ s }}.temp_max_absoluta as decimal(8, 3)) as temp_max_absoluta,
    cast({{ s }}.temp_media_anomalia as decimal(8, 3)) as temp_media_anomalia,
    cast(avg({{ s }}.temp_media) over (w rows between 2 preceding and current row) as decimal(8, 3))
        as temp_media_mm3,
    {%- for k in [1, 2, 3] %}
    cast(lag({{ s }}.temp_media, {{ k }}) over w as decimal(8, 3)) as temp_media_t_menos_{{ k }},
    {%- endfor %}
    {%- for k in [1, 2, 3] %}
    cast(lag({{ s }}.temp_media_anomalia, {{ k }}) over w as decimal(8, 3))
        as temp_media_anomalia_t_menos_{{ k }},
    {%- endfor %}

    -- chuva (mm) e seca (SPI-3)
    cast({{ s }}.precipitacao_total_mm as decimal(10, 3)) as precipitacao_total_mm,
    cast({{ s }}.precipitacao_anomalia_mm as decimal(10, 3)) as precipitacao_anomalia_mm,
    cast({{ s }}.dias_com_chuva as decimal(5, 2)) as dias_com_chuva,
    {%- for k in [1, 2, 3] %}
    cast(lag({{ s }}.precipitacao_total_mm, {{ k }}) over w as decimal(10, 3))
        as precipitacao_t_menos_{{ k }},
    {%- endfor %}
    {%- for k in [1, 2, 3] %}
    cast(lag({{ s }}.precipitacao_anomalia_mm, {{ k }}) over w as decimal(10, 3))
        as precipitacao_anomalia_t_menos_{{ k }},
    {%- endfor %}
    cast({{ s }}.precipitacao_3m_mm as decimal(10, 3)) as precipitacao_3m_mm,
    cast({{ s }}.spi_3 as decimal(6, 3)) as spi_3,
    {%- for k in [1, 2, 3] %}
    cast(lag({{ s }}.spi_3, {{ k }}) over w as decimal(6, 3)) as spi_3_t_menos_{{ k }},
    {%- endfor %}

    -- umidade (%)
    cast({{ s }}.umidade_relativa_media_pct as decimal(8, 3)) as umidade_relativa_media_pct
{% endmacro %}
