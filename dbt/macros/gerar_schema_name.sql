{#
    Usa o schema configurado (+schema: silver / gold) como nome final, em vez do padrão
    do dbt, que prefixa o schema do profile (main_silver, main_gold). O dbt procura a
    macro pelo nome generate_schema_name; o nome do arquivo segue o PLAN_E3_E4.md.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
