-- Uma previsão por praça e subitem: duas linhas dariam ao site duas respostas para o mesmo produto.
select codigo_localidade, codigo_subitem, count(*) as linhas
from {{ ref('fct_previsao_subitem') }}
group by codigo_localidade, codigo_subitem
having count(*) > 1
