# 0003 — Calendário civil para séries diárias do Banco Central

- **Status:** decisão não implementada na trilha atual; a Silver mensal não usa o calendário civil
- **Data:** 2026-09-25
- **Revisado em:** 2026-11-09
- **Decisores:** Squad InflaTrack

## Contexto

As APIs Olinda/PTAX e SGS publicam dólar e Selic somente em dias úteis, mas as
vendas do lojista também ocorrem em fins de semana e feriados. Um `JOIN` diário
direto deixaria essas vendas sem contexto macroeconômico.

O destino segue o [ADR 0002](0002-duckdb-unico.md): todas as fontes analíticas
ficam no mesmo `data/duckdb/inflatrack.duckdb`.

## Decisão

Manter calendário civil permite que vendas em fins de semana e feriados
encontrem o último câmbio e a última Selic publicados. Uma tabela apenas com
dias úteis exigiria que cada consumidor repetisse a regra de "último valor
conhecido", com risco de cada consulta tratar lacunas de um jeito. O
`forward fill` centraliza essa regra; `observado` permite distinguir dado
publicado de valor carregado. Dez dias de lookback cobrem fins de semana e
feriados comuns no início da janela; se não houver cotação anterior, a carga
deve falhar explicitamente.

1. Persistir a resposta original em `data/raw/bcb/` antes da transformação.
2. Manter uma linha por dia civil no DuckDB, carregando o último valor útil
   conhecido (*forward fill*).
3. Registrar `observado = false` nas linhas preenchidas, distinguindo dado
   publicado pelo BCB de valor carregado para alinhamento temporal.
4. Consultar dez dias anteriores ao início solicitado para preencher
   corretamente uma janela que comece em feriado ou fim de semana.
5. Tratar a série SGS 11 como taxa efetiva **diária em percentual**, sem
   apresentá-la como taxa anualizada.

## Consequências

- Vendas em qualquer dia encontram a última informação macro disponível.
- Análises podem excluir valores imputados com `WHERE observado`.
- A primeira data exige um valor útil anterior; sem ele a carga falha de forma
  explícita em vez de gravar `NULL` ou encerrar com falso sucesso.
- O DuckDB continua sujeito a um único processo escritor, então as receitas do
  `justfile` executam as cargas em sequência.

## Estado de implementação

Os carregadores legados `ingest_dolar.py` e `ingest_selic.py` geravam o calendário
civil, aplicavam `forward fill`, registravam `observado` e falhavam se não
houvesse valor anterior. Eles foram removidos na E3, e nenhum código atual repete
essa regra.

A trilha atual é diferente. A Bronze Delta guarda só as observações publicadas pelo
BCB. A Silver (`stg_dolar__cotacao_diaria`, `stg_selic__taxa_diaria` e
`int_macroeconomia__mensal`) agrega para o grão mensal com os dias úteis publicados,
e conta `dias_uteis_dolar` e `dias_uteis_selic` em vez de preencher dias. A Gold
(`fct_macroeconomia_mensal`) cruza Dólar, Selic e IPCA por `mes_referencia`.

O motivo original da decisão, juntar vendas diárias do lojista ao câmbio do dia,
não existe no grão atual: o banco do lojista guarda `venda_mensal`. A decisão fica
em aberto para a Squad: marcar este ADR como superado pelo grão mensal, ou
reimplementar o calendário civil no dbt se a E4 passar a usar vendas diárias.
