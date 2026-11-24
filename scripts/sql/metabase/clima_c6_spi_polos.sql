-- Painel do clima, C6: SPI-3 (seca de 3 meses) em cinco polos agrícolas, desde ago/2016. Abaixo de
-- -1 é seca moderada, -1,5 severa, -2 extrema; a seca de 2024 no Cerrado e no Sul de Minas tem
-- de aparecer em Unaí e Patrocínio. Lê serie.fct_clima_polo_mensal.
select
    p.mes_referencia,
    max(p.spi_3) filter (where p.polo = 'Unaí') as unai_feijao,
    max(p.spi_3) filter (where p.polo = 'Patrocínio') as patrocinio_cafe,
    max(p.spi_3) filter (where p.polo = 'Passo Fundo') as passo_fundo_graos,
    max(p.spi_3) filter (where p.polo = 'Alegrete') as alegrete_arroz,
    max(p.spi_3) filter (where p.polo = 'Linhares') as linhares_conilon
from serie.fct_clima_polo_mensal as p
where p.mes_referencia >= date '2016-08-01'
group by p.mes_referencia
order by p.mes_referencia
