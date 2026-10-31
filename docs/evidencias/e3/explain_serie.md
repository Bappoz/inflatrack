# Evidência E3 — Consulta na vitrine `serie`, sem e com índice

Executado em **2026-10-31** (Linux, Docker, `postgres:16.4-alpine`, limite de 2 GB do compose), sobre a cópia real da Gold: **1.662.314 linhas** em `serie.fct_inflacao_mensal`.

!!! info "Como reproduzir"
    Com o Postgres no ar e `serie` preenchido (`just serie`): `just explain-serie`. O script é [`scripts/explain_serie.py`](https://github.com/Bappoz/inflatrack/blob/main/scripts/explain_serie.py), e a consulta está em [`scripts/sql/explain_serie.sql`](https://github.com/Bappoz/inflatrack/blob/main/scripts/sql/explain_serie.sql). O "sem índice" apaga o índice numa transação desfeita no fim, então o banco termina como começou.

## A consulta

A pergunta mais frequente do lojista (perguntas 1 e 4): os últimos 12 meses de uma categoria na praça dele, com o nome que a categoria tinha na época. Aqui, Arroz (`1101002`) em Brasília (`5300108`).

```sql
select f.mes_referencia, c.nome_categoria, f.variacao_mensal_pct, f.variacao_acum_12m_pct
from serie.fct_inflacao_mensal as f
inner join serie.dim_cesta_ipca_scd2 as c on c.id_versao_cesta = f.id_versao_cesta
where f.codigo_categoria = '1101002'
    and f.codigo_localidade = 5300108
    and f.indice = 'IPCA'
order by f.mes_referencia desc
limit 12
```

O índice, criado na migration `0005_serie_historica.sql`:

```sql
create index fct_inflacao_mensal_consulta_idx on serie.fct_inflacao_mensal (
    codigo_categoria, codigo_localidade, indice, mes_referencia desc
);
```

## Resultado

`EXPLAIN (ANALYZE, BUFFERS)`, três execuções de cada caso, depois de `VACUUM (ANALYZE)`. A comparação usa a 3ª execução, com o cache já aquecido.

| | Sem índice | Com índice |
|---|---|---|
| Tempos das 3 execuções | 126,9 / 106,3 / 107,8 ms | 0,36 / 0,29 / 0,27 ms |
| Acesso à fato | `Parallel Seq Scan` (2 *workers*) | `Index Scan` |
| Linhas descartadas pelo filtro | 554.024 por processo | nenhuma |
| Blocos lidos (*shared hit + read*) | 33.212 | 41 |
| Ordenação | `Sort` (top-N) | nenhuma: o índice já entrega em ordem decrescente |

Planos completos: [`explain_serie_sem_indice.txt`](explain_serie_sem_indice.txt) e [`explain_serie_com_indice.txt`](explain_serie_com_indice.txt).

## Como ler

- **A ordem das colunas do índice é a da consulta:** as três igualdades primeiro e `mes_referencia desc` por último. Por isso o Postgres para depois de 12 linhas, sem ordenar: o `LIMIT` é satisfeito pelo próprio índice.
- **O que pesa não é o tempo de 107 ms de uma consulta**, e sim os 33 mil blocos lidos em cada uma. Com vários lojistas ao mesmo tempo, isso disputa o cache e o disco; a consulta indexada lê 41.
- **O custo do índice** é mantê-lo a cada cópia da Gold, que apaga e insere todas as linhas. A cópia completa das 6 tabelas levou cerca de 44 s. O custo isolado do índice nessa cópia **não foi medido**.

## Limitações

- Mesma máquina, sem carga concorrente: os números valem para comparar os dois planos, não como latência de produção.
- A consulta é uma só, e seletiva de propósito. Uma consulta que varre a maior parte da tabela não ganharia com este índice.
