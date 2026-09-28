# Visão Geral da Arquitetura

O InflaTrack junta duas metades de natureza oposta:

| Metade | O que guarda | Volume | Escrita |
|---|---|---|---|
| **Referência pública** | Séries do IBGE (IPCA, INPC, Contas Nacionais), do Banco Central (dólar, Selic), da Alpha Vantage (commodities e energia), do Banco Mundial (PIB da China), do DIEESE (salário mínimo) e do INMET (clima) | ~4,7 mi linhas de IPCA; ~6,4 mi com INPC; as demais séries somam poucas dezenas de MB | Lote: mensal (IBGE, DIEESE), trimestral (Contas Nacionais), diária (BCB, energia, INMET), anual (Banco Mundial) |
| **Transacional própria** | Lojista, produto e reajuste | Baixíssimo | Aplicar reajuste: a única escrita que exige transação |

A ponte entre as duas é a FK `produto.codigo_subitem_ipca`: é ela que permite responder "quanto a inflação do que eu vendo subiu". As demais fontes entram como variáveis explicativas — dizem **por que** o preço se moveu, enquanto o IPCA diz **quanto**.

## Fontes

Oito conjuntos de dados vindos de seis provedores, todos públicos. Só a Alpha Vantage exige autenticação (chave gratuita com cota diária) e só o DIEESE não oferece API — é raspagem da página oficial. Cada fonte tem sua página com volumetria, restrições e padrão de acesso; a lista completa está em [Tabela fontes](fonteDados.md).

| Fonte | Origem | Frequência | Destino |
|---|---|---|---|
| [IPCA/INPC](../fontes/sidra.md) | SIDRA (IBGE) | Mensal | PostgreSQL |
| [Commodities e Energia](../fontes/commodities.md) | Alpha Vantage | Diária e mensal | DuckDB |
| [Dólar Comercial](../fontes/dolar.md) | Olinda/PTAX (BCB) | Diária (dias úteis) | DuckDB |
| [Taxa SELIC](../fontes/selic.md) | SGS série 11 (BCB) | Diária (dias úteis) | DuckDB |
| [PIB e Setores](../fontes/pib.md) | SIDRA 1846 (IBGE) | Trimestral | DuckDB |
| [PIB da China](../fontes/pib_china.md) | Banco Mundial | Anual | DuckDB |
| [Salário Mínimo](../fontes/salario_minimo.md) | DIEESE (HTML) | Mensal | DuckDB |
| [Dados do Clima](../fontes/clima.md) | INMET | Diária | DuckDB |

Todas seguem a mesma trilha de camadas, detalhada em [Arquitetura Medallion](arquiteturaMedallion.md): resposta crua em `data/raw/<fonte>/`, transformação (em Parquet ou em memória) e carga idempotente na silver. O código que percorre essa trilha tem sempre a mesma anatomia, descrita em [Componentes](componentes.md).

## Stack

| Peça | Tecnologia | Papel |
|---|---|---|
| Banco relacional | PostgreSQL 16.4 (Docker Compose, limite de 2 GB de memória) | Referência do IBGE (IPCA/INPC) + lado transacional |
| Banco analítico | DuckDB embarcado, arquivo único em `data/duckdb/inflatrack.duckdb` | Séries macro, commodities, PIB, salário mínimo e clima, com views de features para os modelos ([ADR 0002](../adr/0002-duckdb-unico.md)) |
| Camada crua | Arquivos gzip em `data/raw/` (uma subpasta por fonte): JSON nas APIs, HTML no DIEESE | Auditoria e reprocessamento sem chamar as origens |
| Camada intermediária | Parquet em `data/parquet/` | Bronze das fontes analíticas; recarrega o DuckDB sem rede |
| Ingestão | Python 3.12, `httpx` e `requests`, `pandas`, `psycopg`, `pyarrow` | Clientes das origens e carga ELT (`src/inflatrack/ingest_*.py` e `load_*.py`) |
| Extração de HTML | `re` e `html` da biblioteca padrão | Parsing da tabela do DIEESE, sem dependência de terceiros |
| Documentação | MkDocs Material | Este site, compilado com `--strict` |
| Automação | `just` + `uv` | Comandos canônicos (`just --list`) |

## Requisitos não funcionais

| Requisito | Valor |
|---|---|
| Latência | < 300 ms nas telas (perguntas 1, 4 e 5); < 5 s nos relatórios (2 e 3) |
| Consistência | A, C e I obrigatórias ao aplicar reajuste; leitura analítica tolera dado de segundos atrás |
| Durabilidade | Obrigatória na carga: reingerir ~2,2 GB do SIDRA não é aceitável |
| Disponibilidade | Média: ferramenta de planejamento, não caixa de loja |
| Idempotência | Toda carga é reexecutável sobre a mesma janela sem duplicar linha (`UPSERT` por chave natural de data, índice único no Postgres) |
| Resiliência das origens | Falha de origem não corrompe o histórico já carregado; a carga termina com código diferente de zero e o modelo segue com o último dado conhecido |
| Acoplamento à origem | Fontes sem API (DIEESE) dependem do layout HTML: mudança de estrutura derruba a carga em vez de gravar dado errado, e a raw permite reprocessar offline |
| LGPD | Nenhuma fonte pública contém dado pessoal; CNPJ de lojista MEI é tratado como dado pessoal |

## Decisões

- [ADR 0001 — origem insert-only com a cesta do IPCA em dimensão de vigência](../arquitetura.md) (proposto; falta a medição).
- [ADR 0002 — um único arquivo DuckDB para todas as séries analíticas](../adr/0002-duckdb-unico.md) (proposto).
- [ADR 0003 — calendário civil para as séries diárias do Banco Central](../adr/0003-bcb-macro.md) (proposto).
