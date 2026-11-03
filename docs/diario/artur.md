# Diário de bordo — Artur Fernandes Galdino

## Semana de 2026-09-22 a 2026-09-28 (Entrega 1)

**O que medi**

- 66 anos de dados históricos coletados da API do Banco Mundial (1960–2025), totalizando 132 linhas no formato longo para os dois indicadores (`NY.GDP.MKTP.KD.ZG` para crescimento percentual e `NY.GDP.MKTP.CD` para PIB nominal em dólares).
- O payload JSON da API tem ~18 KB por indicador; a ingestão completa da série histórica levou 1,2 s na primeira carga.
- A tabela `pib_china` no PostgreSQL 16 foi criada via migration `0004_pib_china.sql` ocupando menos de 1 MB.

**O que me surpreendeu**

- A API do Banco Mundial não exige autenticação via `API_KEY` para consultas públicas, facilitando a automação, mas a estrutura da resposta devolve uma lista de dois elementos: o primeiro é um cabeçalho de paginação e o segundo é a lista de registros econômicos.
- O crescimento exponencial da economia chinesa na série: o PIB nominal salta de US$ 59,7 bilhões em 1960 para US$ 18,3 trilhões em 2023, justificando sua relevância direta na demanda por commodities e impacto nos preços.

**O que decidi**

- Armazenar os indicadores no formato longo (uma linha por indicador/ano) em vez de pivotar na ingestão, deixando a consolidação analítica para etapas posteriores.
- Salvar a resposta bruta em `data/raw/pib_china/` em gzip para manter o histórico da fonte e permitir reprocessamentos locais sem consumir a rede.

---

## Semana de 2026-10-06 a 2026-10-13 (Entrega 2)

**O que medi**

- 396 linhas gravadas no Delta Lake divididas igualmente entre os 3 países parceiros (132 linhas para China, 132 para EUA e 132 para Rússia).
- Idempotência comprovada: reexecutar a ingestão contra a API resultou em 0 linhas adicionadas e nenhuma versão criada no log de transações do Delta (`_delta_log/`).
- O hash SHA-256 de 64 caracteres gerado do corpo da resposta HTTP bloqueou duplicatas em 100% dos testes.

**O que me surpreendeu**

- A Rússia não possui registros publicados pelo Banco Mundial entre 1960 e 1989 (período soviético anterior à dissolução da URSS). A série de dados válidos só se inicia em 1990.
- Se aplicássemos a checagem rígida de volume da China ou dos EUA na Rússia, o pipeline quebrava acusando campos nulos. Foi necessário flexibilizar a regra de integridade para respeitar esse corte histórico.

**O que decidi**

- Preservar os 30 anos de nulos históricos da Rússia no Delta Lake em vez de descartar os registros pré-1990, mantendo o mesmo grão temporal (1960–2025) em todos os países.
- Estruturar duas tabelas Delta por país: `pib_<pais>_resposta` para o payload bruto auditável e `pib_<pais>_indicador` para os dados extraídos.

---

## Semana de 2026-10-26 a 2026-11-02 (Entrega 3)

**O que medi**

- A fusão unificada reduziu 11 arquivos legados para apenas 2 módulos de código (`pib_internacional.py` e `load_pib_internacional.py`), eliminando mais de 1.100 linhas de código duplicado.
- A carga unificada no DuckDB analítico inseriu 396 registros na tabela `bronze.pib_internacional_indicador` em 0,18 s; na segunda execução, inseriu exatamente 0 linhas (idempotência estrita).
- O modelo dbt Gold `fct_pib_internacional_anual` pivotou as séries em formato largo (*wide*), gerando 198 registros anuais consolidados e passando em todos os 15 testes de integridade (`dbt build` 100% aprovado).
- A suíte completa de testes do repositório passou a contar com 177 testes automatizados executando em ~71 s.

**O que me surpreendeu**

- O DuckDB não possui a função `date_from_parts(ano, 1, 1)` presente em bancos relacionais tradicionais; sua função escalar nativa para construção de data é `make_date(ano, 1, 1)`. O build do dbt falhou na primeira tentativa até essa substituição ser feita.
- No Dagster, manter o `group_name="pib_china"` herdado da E2 nos ativos da China gerava duas caixas separadas no grafo visual (`pib_china` $\rightarrow$ `pib_internacional`), transmitindo a falsa impressão de que a fusão não estava completa.
- O `common.bronze.carregar_duckdb` já faz o `CREATE TABLE IF NOT EXISTS` automaticamente a partir do esquema do Delta Lake, tornando desnecessários os arquivos manuais `setup_duckdb_*.sql`.

**O que decidi**

- Extrair o cliente comum `WorldBankClient` em `clients/worldbank.py` para centralizar URLs, tratamento de timeouts e códigos dos indicadores.
- Usar `group_name="pib_internacional"` em todos os ativos do Dagster para que toda a extração e carga de PIB Internacional fique visivelmente agrupada em um único bloco coeso no canvas.
- Aposentar e excluir via `git rm` os 11 arquivos legados (`bronze_pib_*`, `ingest_pib_*`, `load_pib_china.py`, `setup_duckdb_pib_china.sql` e testes antigos por país), mantendo o repositório 100% limpo e sem redundância.
