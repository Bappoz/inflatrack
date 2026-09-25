# 0002 — Motor Analítico DuckDB e Tratamento Forward Fill de Séries Temporais

- **Status:** aceito
- **Data:** 2026-09-25
- **Decisores:** _(a definir pela Squad)_

## Contexto

A frente Macroeconomia lida com variáveis de flutuação diária (Câmbio, Juros, Commodities) que balizam os custos estruturais do lojista (importação de insumos e captação de crédito). Três desafios técnicos nos forçaram a não utilizar a mesma arquitetura do IPCA (PostgreSQL) para esses indicadores:

1. **Gargalo I/O Relacional em Séries Temporais:** O PostgreSQL (usado para o SIDRA) é otimizado para *Row-Store* (Transacional). Ao cruzar séries longas diariamente (milhares de dias de Dólar × milhares de dias de Selic para cálculos estatísticos retroativos), a varredura se torna intensiva em disco.
2. **Buracos no Calendário:** O lojista opera seu comércio de segunda a segunda. Porém, a API do Banco Central (Olinda e SGS) e o mercado financeiro não emitem boletins aos sábados, domingos e feriados nacionais.
3. **Anomalia de Múltiplos Boletins Diários:** A API Olinda emite cotações *intradiárias* da mesma data, o que gera quebra de chaves únicas e impossibilita um alinhamento 1:1 com o calendário.

## Decisão

1. **Adoção do DuckDB (Column-Store):** Implementar o DuckDB como motor analítico (Camada Silver). As séries temporais são persistidas em colunas (`Parquet`), proporcionando leitura vetorial de altíssimo desempenho para agregação estatística, poupando a arquitetura principal.
2. **Conversão Bronze em Memória (Forward Fill):** Utilizar processamento em memória no Python (via `pandas.DataFrame.ffill()`) para preencher os buracos do calendário *antes* da inserção. As sextas-feiras são esticadas logicamente para cobrir os finais de semana.
3. **Descarte de Volatilidade Intradiária:** Adoção estrita da cotação de *Fechamento* (`keep="last"`), descartando os ruídos matutinos para evitar duplicação de dias.

## Consequências

**O que ganhamos:**
- **Continuidade Matemática Perfeita:** Não haverá falha de `JOIN` (NullPointer) quando a transação do lojista ocorrer num sábado e buscar a cotação cambial daquele momento.
- **Isolamento de Falhas (Bulkhead):** Se o banco PostgreSQL cair ou sobrecarregar, o módulo de análise preditiva segue vivo operando diretamente sobre o arquivo `inflatrack.duckdb`.
- **Performance:** Consultas de séries históricas que levariam segundos em modelo relacional (row-store) caem para submilisegundos (column-store).

**O que perdemos:**
- Aumento da complexidade do ecossistema, exigindo que o orquestrador (`justfile` e futuramente Dagster) coordene dois processos de injeção paralelos.
- Consumo adicional mínimo de disco por esticar o calendário guardando linhas replicadas de sextas para finais de semana.
