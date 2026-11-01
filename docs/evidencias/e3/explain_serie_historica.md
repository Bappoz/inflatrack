# Evidência E3 — Otimização de Consulta SQL com `EXPLAIN (ANALYZE, BUFFERS)`

Em conformidade com o checklist de aceite da Entrega 3:
> *"Ao menos uma consulta otimizada a partir do plano de execução, com `EXPLAIN (ANALYZE, BUFFERS)` antes e depois no repositório"*

Documentamos nesta evidência o diagnóstico de plano de execução, o consumo de recursos de memória/disco (*buffers*) e o resultado da otimização realizada na tabela servida **`serie.serie_mensal`** no PostgreSQL.

---

## 1. Contexto Arquitetural e Consulta Analítica

Conforme definido na arquitetura do projeto ([`PLAN_E3_E4.md`](file:///home/americo/Faculdade/Bancos%202/inflatrack/PLAN_E3_E4.md)), o DuckDB processa as transformações analíticas nas camadas Bronze, Silver e Gold, enquanto o **PostgreSQL atua como vitrine de consumo (schema `serie`)** lida exclusivamente pelo Metabase e pelas consultas dos comerciantes.

A consulta alvo representa a consulta mais frequente do painel analítico (Pergunta 1 do lojista):
> *"Recuperar o histórico recente de variação mensal de preços de uma mercadoria específica em uma determinada praça, ordenado da data mais recente para a mais antiga."*

```sql
SELECT mes_referencia, codigo_localidade, codigo_variavel, valor
FROM serie.serie_mensal
WHERE codigo_classificacao = '1101002'
  AND codigo_localidade = 3304557
  AND codigo_variavel = 63
  AND mes_referencia >= '2015-01-01'
ORDER BY mes_referencia DESC;
```

O teste foi executado sobre uma massa volumétrica realista de **250.000 registros históricos** em ambiente PostgreSQL 16.4.

---

## 2. Cenário 1: Antes da Otimização (Sem Índice)

Sem índices dedicados, o otimizador do PostgreSQL (*Cost-Based Optimizer - CBO*) é forçado a percorrer todas as páginas físicas de dados da tabela (`Seq Scan`) e ordenar os dados em memória.

### Plano de Execução do PostgreSQL:
```text
Gather Merge  (cost=6278.77..6281.64 rows=25 width=16) (actual time=9.826..11.424 rows=49 loops=1)
  Output: mes_referencia, codigo_localidade, codigo_variavel, valor
  Workers Planned: 1
  Workers Launched: 1
  Buffers: shared hit=2374
  ->  Sort  (cost=5278.76..5278.82 rows=25 width=16) (actual time=8.021..8.022 rows=24 loops=2)
        Output: mes_referencia, codigo_localidade, codigo_variavel, valor
        Sort Key: serie_mensal.mes_referencia DESC
        Sort Method: quicksort  Memory: 26kB
        Buffers: shared hit=2374
        Worker 0:  actual time=6.433..6.434 rows=16 loops=1
          Sort Method: quicksort  Memory: 25kB
          Buffers: shared hit=846
        ->  Parallel Seq Scan on serie.serie_mensal  (cost=0.00..5278.18 rows=25 width=16) (actual time=1.053..7.901 rows=24 loops=2)
              Output: mes_referencia, codigo_localidade, codigo_variavel, valor
              Filter: ((serie_mensal.mes_referencia >= '2015-01-01'::date) 
                       AND ((serie_mensal.codigo_classificacao)::text = '1101002'::text) 
                       AND (serie_mensal.codigo_localidade = 3304557) 
                       AND (serie_mensal.codigo_variavel = 63))
              Rows Removed by Filter: 124976
              Buffers: shared hit=2337
              Worker 0:  actual time=1.899..6.214 rows=16 loops=1
                Buffers: shared hit=809
Planning:
  Buffers: shared hit=110
Planning Time: 0.349 ms
Execution Time: 11.468 ms
```

### Diagnóstico do Gargalo:
1. **Varredura Sequencial Completa:** O banco precisou examinar 250.000 linhas, descartando 249.951 linhas via filtro (`Rows Removed by Filter: 124976` por worker).
2. **Consumo de I/O em Memória/Disco:** Foram acessados **2.374 buffers compartilhados de 8 KB** ($\approx 18,99\text{ MB}$ de páginas transferidas através do buffer pool do PostgreSQL).
3. **Sobrecarga de CPU:** Exigiu etapa explícita de `Sort` com quicksort e paralelização de workers (`Gather Merge`).

---

## 3. Ação de Otimização: Engenharia de Índices B-Tree Cobrindo

Para eliminar tanto a varredura sequencial quanto a necessidade de ordenação e leituras na tabela principal (*heap*), desenhamos um **Índice B-Tree Cobrindo (*Covering Index*)**:

```sql
CREATE INDEX idx_serie_mensal_covering 
ON serie.serie_mensal (codigo_classificacao, codigo_localidade, codigo_variavel, mes_referencia DESC)
INCLUDE (valor);
```

### Racional de Design:
- **Chave Composta:** As colunas com predicados de igualdade estrita (`codigo_classificacao`, `codigo_localidade`, `codigo_variavel`) formam o prefixo do índice.
- **Predicado de Range + Ordenação:** A coluna `mes_referencia DESC` permite navegar na árvore B-Tree exatamente na ordem solicitada pela query, eliminando a operação `Sort`.
- **Cláusula `INCLUDE (valor)`:** Armazena a métrica `valor` nas folhas do índice sem onerá-lo como chave de busca, viabilizando o acesso **`Index Only Scan`** (zero acessos à tabela base).

---

## 4. Cenário 2: Depois da Otimização (Com Índice Cobrindo)

Com o índice cobrindo registrado e as estatísticas atualizadas via `VACUUM ANALYZE`, o PostgreSQL passa a responder à consulta exclusivamente através da estrutura do índice.

### Plano de Execução do PostgreSQL:
```text
Index Only Scan using idx_serie_mensal_covering on serie.serie_mensal  (cost=0.42..5.54 rows=45 width=16) (actual time=0.045..0.049 rows=49 loops=1)
  Output: mes_referencia, codigo_localidade, codigo_variavel, valor
  Index Cond: ((serie_mensal.codigo_classificacao = '1101002'::text) 
               AND (serie_mensal.codigo_localidade = 3304557) 
               AND (serie_mensal.codigo_variavel = 63) 
               AND (serie_mensal.mes_referencia >= '2015-01-01'::date))
  Heap Fetches: 0
  Buffers: shared hit=4 read=3
Planning:
  Buffers: shared hit=62
Planning Time: 0.200 ms
Execution Time: 0.071 ms
```

---

## 5. Comparativo Quantitativo de Desempenho

| Métrica Avaliada | Antes (Sem Índice) | Depois (Índice Cobrindo) | Redução / Ganho |
| :--- | :---: | :---: | :---: |
| **Operação Principal** | `Parallel Seq Scan` + `Sort` | `Index Only Scan` | Eliminação do Scan e do Sort |
| **Custo Estimado (*Total Cost*)** | **6.281,64** | **5,54** | **-99,91%** |
| **Páginas de Buffer Acessadas** | **2.374 buffers** (~19 MB) | **7 buffers** (~56 KB) | **-99,70% de I/O** |
| **Acessos à Heap (*Heap Fetches*)** | 250.000 linhas varridas | **0 acessos** | **100% resolvido no índice** |
| **Tempo de Execução (*Execution Time*)** | **11,468 ms** | **0,071 ms** | **161,5× mais rápido** |

---

## 6. Conclusão Técnica e Reprodutibilidade

1. **Eficiência no Metabase:** A redução de `2.374` para apenas `7` blocos de buffer lidos por consulta significa que dezenas de usuários ou dashboards no Metabase podem consultar séries históricas concorrentemente sem causar concorrência de I/O (*buffer cache eviction*) no PostgreSQL.
2. **Reprodutibilidade:** O script completo para reproduzir os dois planos em qualquer instância limpa do PostgreSQL está versionado em [`scripts/sql/explain_serie.sql`](file:///home/americo/Faculdade/Bancos%202/inflatrack/scripts/sql/explain_serie.sql) e a estrutura formal está integrada em [`migrations/0005_serie_historica.sql`](file:///home/americo/Faculdade/Bancos%202/inflatrack/migrations/0005_serie_historica.sql).
