# 0003 — Calendário civil para séries diárias do Banco Central

- **Status:** proposto
- **Data:** 2026-09-25
- **Revisado em:** 2026-10-18
- **Decisores:** Squad InflaTrack; proposta ainda sem implementação no calendário Silver

## Contexto

As APIs Olinda/PTAX e SGS publicam dólar e Selic somente em dias úteis, mas as
vendas do lojista também ocorrem em fins de semana e feriados. Um `JOIN` diário
direto deixaria essas vendas sem contexto macroeconômico.

O destino segue o [ADR 0002](0002-duckdb-unico.md): todas as fontes analíticas
ficam no mesmo `data/duckdb/inflatrack.duckdb`.

## Decisão

**Proposta:** manter calendário civil para permitir que vendas em fins de
semana e feriados encontrem o último câmbio e a última Selic publicados. Uma
tabela apenas com dias úteis exigiria que cada consumidor repetisse a regra de
"último valor conhecido", com risco de cada consulta tratar lacunas de um jeito.
O `forward fill` centraliza essa regra; `observado` permite distinguir dado
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

Este ADR ainda é uma proposta. Os ingestores atuais gravam as observações
publicadas em dias úteis; o preenchimento do calendário civil e a coluna
`observado` pertencem à Silver planejada e ainda não estão implementados. Não
apresentar o `forward fill` como comportamento atual até a camada de
transformação existir e ser verificada.
