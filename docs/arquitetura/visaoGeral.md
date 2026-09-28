# Visão Geral da Arquitetura

O InflaTrack junta duas metades de natureza oposta:

| Metade | O que guarda | Volume | Escrita |
|---|---|---|---|
| **Referência pública** | Séries do IBGE (IPCA, INPC, Contas Nacionais), do Banco Central (dólar, Selic), da Alpha Vantage (commodities e energia), do Banco Mundial (PIB da China), do DIEESE (salário mínimo) e do INMET (clima) | ~4,7 mi linhas de IPCA; ~6,4 mi com INPC; as demais séries somam poucas dezenas de MB | Lote: mensal (IBGE, DIEESE), trimestral (Contas Nacionais), diária (BCB, energia, INMET), anual (Banco Mundial) |
| **Transacional própria** | Lojista, produto e reajuste | Baixíssimo | Aplicar reajuste: a única escrita que exige transação |

A ponte entre as duas é a FK `produto.codigo_subitem_ipca`: é ela que permite responder "quanto a inflação do que eu vendo subiu". As demais fontes entram como variáveis explicativas — dizem **por que** o preço se moveu, enquanto o IPCA diz **quanto**.

## Fontes

Oito conjuntos de dados vindos de seis provedores, todos públicos. Só a Alpha Vantage exige autenticação (chave gratuita com cota diária) e só o DIEESE não oferece API — é raspagem da página oficial. Cada fonte tem sua página com volumetria, restrições e padrão de acesso; a lista completa está em [Tabela fontes](fonteDados.md).

| Fonte | Origem | Frequência | Papel no modelo |
|---|---|---|---|
| [IPCA/INPC](../fontes/sidra.md) | SIDRA (IBGE) | Mensal | Alvo |
| [Commodities e Energia](../fontes/commodities.md) | Alpha Vantage | Diária e mensal | Feature |
| [Dólar Comercial](../fontes/dolar.md) | Olinda/PTAX (BCB) | Diária (dias úteis) | Feature |
| [Taxa SELIC](../fontes/selic.md) | SGS série 11 (BCB) | Diária (dias úteis) | Feature |
| [PIB e Setores](../fontes/pib.md) | SIDRA 1846 (IBGE) | Trimestral | Feature |
| [PIB da China](../fontes/pib_china.md) | Banco Mundial | Anual | Feature |
| [Salário Mínimo](../fontes/salario_minimo.md) | DIEESE (HTML) | Mensal | Feature |
| [Dados do Clima](../fontes/clima.md) | INMET | Diária | Feature |

Todas terminam no mesmo lugar — a Gold do DuckDB — porque o alvo e as features precisam estar juntos para treinar.

Todas seguem a mesma trilha de quatro camadas, detalhada em [Arquitetura Medallion](arquiteturaMedallion.md): **Raw** em `.json.gz`, **Bronze** em Parquet, **Silver** modelada com `dbt-duckdb` e **Gold** em tabelas tratadas no DuckDB. As peças que percorrem essa trilha estão em [Componentes](componentes.md).

## Stack

| Peça | Tecnologia | Papel |
|---|---|---|
| Camada Raw | Arquivos gzip em `data/raw/` (uma subpasta por fonte): JSON nas APIs, HTML no DIEESE | Aterrissagem imutável, para auditoria e reprocessamento sem chamar as origens |
| Camada Bronze | Parquet em `data/parquet/<fonte>/` | Payload parseado e tipado; é o *source* que o dbt lê |
| Transformação | `dbt-core` com adapter `dbt-duckdb` | Silver e Gold declaradas em modelos versionados, com testes e linhagem |
| Banco analítico | DuckDB embarcado, arquivo único em `data/duckdb/inflatrack.duckdb` | Materializa Silver e Gold; cruza as 8 fontes no mesmo `JOIN` ([ADR 0002](../adr/0002-duckdb-unico.md)) |
| Banco transacional | PostgreSQL 16.4 (Docker Compose, limite de 2 GB de memória) | Em paralelo ao medallion: lojista, produto, reajuste e a referência do IPCA com suas FKs |
| Orquestração | Dagster, com `dagster-dbt` | Grafo de ativos particionado por mês, com retry e backfill |
| Ingestão | Python 3.12, `httpx` e `requests`, `pandas`, `pyarrow`, `psycopg` | Clientes das origens e gravação de Raw e Bronze (`src/inflatrack/`) |
| Extração de HTML | `re` e `html` da biblioteca padrão | Parsing da tabela do DIEESE, sem dependência de terceiros |
| Aprendizado de máquina | Jupyter Notebooks, `scikit-learn`, MLflow | Treinar, comparar e rastrear os modelos preditivos sobre a Gold |
| Painel | Streamlit + Plotly | As cinco perguntas de gestão declaradas na E1 |
| Documentação | MkDocs Material | Este site, compilado com `--strict` |
| Automação | `just` + `uv` | Comandos canônicos (`just --list`) |

## Requisitos não funcionais

| Requisito | Valor |
|---|---|
| Latência | < 300 ms nas telas (perguntas 1, 4 e 5); < 5 s nos relatórios (2 e 3) |
| Consistência | A, C e I obrigatórias ao aplicar reajuste; leitura analítica tolera dado de segundos atrás |
| Durabilidade | Obrigatória na carga: reingerir ~2,2 GB do SIDRA não é aceitável |
| Disponibilidade | Média: ferramenta de planejamento, não caixa de loja |
| Idempotência | Toda carga é reexecutável sobre a mesma janela sem duplicar linha: nome de arquivo por janela na Raw, e Silver reconstruída a partir da Bronze |
| Concorrência no DuckDB | Um escritor por arquivo, por vez: o Dagster serializa carga e `dbt build`, e o painel lê uma cópia publicada da Gold |
| Resiliência das origens | Falha de origem não corrompe o histórico já carregado; a carga termina com código diferente de zero e o modelo segue com o último dado conhecido |
| Acoplamento à origem | Fontes sem API (DIEESE) dependem do layout HTML: mudança de estrutura derruba a carga em vez de gravar dado errado, e a raw permite reprocessar offline |
| LGPD | Nenhuma fonte pública contém dado pessoal; CNPJ de lojista MEI é tratado como dado pessoal |

## Decisões

- [ADR 0001 — origem insert-only com a cesta do IPCA em dimensão de vigência](../arquitetura.md) (proposto; falta a medição).
- [ADR 0002 — um único arquivo DuckDB para todas as séries analíticas](../adr/0002-duckdb-unico.md) (proposto).
- [ADR 0003 — calendário civil para as séries diárias do Banco Central](../adr/0003-bcb-macro.md) (proposto).
