# Diário de bordo — Lucas Zanetti

## Semana de 2026-10-26 a 2026-10-31

**O que medi**

- A consulta da vitrine caiu de 107,8 ms para 0,27 ms com o índice, e de 33.212 para 41 blocos lidos, sobre 1.662.314 linhas ([evidência](../evidencias/e3/explain_serie.md)).
- O acumulado de 12 meses calculado por nós difere do publicado pelo IBGE em no máximo 0,0326 ponto percentual.
- A migration `0004` leva 52 s numa cópia do volume real, com quase 6 milhões de linhas em `observacao`.

**O que me surpreendeu**

- O peso do IPCA muda todo mês, então não dá para abrir uma versão de SCD2 a cada mudança de peso. A mudança que importa é a troca de estrutura da cesta (POF).
- Eu achava que o IPCA tinha 12 localidades até 2011 e 17 depois. O teste falhou: elas entraram em 2014 e em 2018.
- A primeira versão da defasagem do lojista errava justamente no mês corrente, porque o IBGE ainda não publicou aquele mês.

**O que decidi**

- CDC lógico lendo o slot por função SQL, sem Kafka nem Debezium ([ADR](../adr/cdc-vs-lote.md)).
- `dim_produto_preco_scd2` sai do log do CDC e não de `dbt snapshot`, para encaixar evento atrasado na ordem certa.
- O lojista não lê as tabelas de preços em `serie` até a E4 ter RLS: sem isso, cada loja veria os preços das outras.
