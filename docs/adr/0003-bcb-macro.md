# 0003 — Calendário civil para séries diárias do Banco Central

- **Status:** proposto
- **Data:** 2026-09-25
- **Decisores:** _(a definir pela Squad)_

## Contexto

As APIs Olinda/PTAX e SGS publicam dólar e Selic somente em dias úteis, mas as
vendas do lojista também ocorrem em fins de semana e feriados. Um `JOIN` diário
direto deixaria essas vendas sem contexto macroeconômico.

O destino segue o [ADR 0002](0002-duckdb-unico.md): todas as fontes analíticas
ficam no mesmo `data/duckdb/inflatrack.duckdb`.

## Decisão

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
