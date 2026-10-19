# Visão Geral da Arquitetura

O InflaTrack junta duas metades de natureza oposta:

| Metade | O que guarda | Volume | Escrita |
|---|---|---|---|
| **Referência pública** | Séries do IBGE (IPCA, INPC, Contas Nacionais), do Banco Central (dólar, Selic), da Alpha Vantage (commodities e energia), do Banco Mundial (PIB da China, dos EUA e da Rússia), do DIEESE (salário mínimo) e do INMET (clima) | ~4,7 mi linhas de IPCA; ~6,4 mi com INPC; as demais séries somam poucas dezenas de MB | Lote: mensal (IBGE, DIEESE), trimestral (Contas Nacionais), diária (BCB, energia, INMET), anual (Banco Mundial) |
| **Transacional própria** | Lojista, produto e reajuste | Baixíssimo | Aplicar reajuste: a única escrita que exige transação |

A ponte entre as duas é a FK `produto.codigo_subitem_ipca`: é ela que permite responder "quanto a inflação do que eu vendo subiu". As demais fontes entram como variáveis explicativas — dizem **por que** o preço se moveu, enquanto o IPCA diz **quanto**.

## Fontes

Dez conjuntos de dados vindos de seis provedores, todos públicos. Só a Alpha Vantage exige autenticação (chave gratuita com cota diária) e só o DIEESE não oferece API — é raspagem da página oficial. Cada fonte tem sua página com volumetria, restrições e padrão de acesso; a lista completa está em [Tabela fontes](fonteDados.md).

| Fonte | Origem | Frequência | Papel no modelo |
|---|---|---|---|
| [IPCA/INPC](../fontes/sidra.md) | SIDRA (IBGE) | Mensal | Alvo |
| [Commodities e Energia](../fontes/commodities.md) | Alpha Vantage | Diária e mensal | Feature |
| [Dólar Comercial](../fontes/dolar.md) | Olinda/PTAX (BCB) | Diária (dias úteis) | Feature |
| [Taxa SELIC](../fontes/selic.md) | SGS série 11 (BCB) | Diária (dias úteis) | Feature |
| [PIB e Setores](../fontes/pib.md) | SIDRA 1846 (IBGE) | Trimestral | Feature |
| [PIB da China](../fontes/pib_china.md) | Banco Mundial | Anual | Feature |
| [PIB dos EUA](../fontes/pib_usa.md) | Banco Mundial | Anual | Feature |
| [PIB da Rússia](../fontes/pib_russia.md) | Banco Mundial | Anual | Feature |
| [Salário Mínimo](../fontes/salario_minimo.md) | DIEESE (HTML) | Mensal | Feature |
| [Dados do Clima](../fontes/clima.md) | INMET | Diária | Feature |

O destino previsto para as séries públicas é uma Gold analítica no DuckDB, onde alvo e features poderão ser cruzados. Hoje os ingestores já carregam fontes no PostgreSQL e no DuckDB; o projeto dbt que produzirá a Silver e a Gold comuns ainda está planejado.

O fluxo alvo tem quatro camadas, detalhadas em [Arquitetura Medallion](arquiteturaMedallion.md): **Raw** em arquivos gzip, **Bronze** em tabelas Delta Lake sobre Parquet, **Silver** com dbt-duckdb e **Gold** no DuckDB. Raw e partes da Bronze estão em uso; dbt, Silver e Gold conformada ainda estão planejados. Algumas fontes seguem também por carregadores legados diretamente ao DuckDB.

## Stack

| Peça | Tecnologia | Por que foi escolhida | Estado |
|---|---|---|---|
| Camada Raw | JSON/HTML gzip em `data/raw/<fonte>/` | Preserva respostas para auditoria e reprocessamento sem nova chamada às origens. | Em uso |
| Camada Bronze | Delta Lake sobre arquivos Parquet em `data/parquet/<fonte>/` | Mantém formato colunar e interoperável com histórico transacional para cargas idempotentes e revisões. | Em uso em partes da E2; alguns carregadores legados ainda usam Parquet diretamente |
| Transformação | `dbt-core` + `dbt-duckdb` | SQL versionado para modelos, testes e linhagem entre Bronze, Silver e Gold. | Planejado; não está nas dependências |
| Banco analítico | DuckDB em `data/duckdb/inflatrack.duckdb` | SQL analítico multifonte sem operar um servidor separado para a carga atual. Ver [ADR 0002](../adr/0002-duckdb-unico.md). | Em uso |
| Banco transacional | PostgreSQL 16.4 em Docker Compose | Transações, FKs e restrições para cadastro de lojista, produto e reajuste. | Em uso |
| Orquestração | Dagster | Assets, partições, retries e backfills representam as saídas de dados do pipeline. | Em uso nas ingestões; integração com dbt planejada |
| Ingestão | Python 3.12, `httpx`/`requests`, `pandas`, `pyarrow`, `deltalake`, `psycopg` | Um runtime integra clientes HTTP, conversão tabular, tabelas Bronze e os dois bancos. | Em uso; os clientes `requests` são legado a consolidar |
| Painel | Streamlit + Plotly | Interface Python para as perguntas do lojista e visualizações interativas. | Planejado; não está nas dependências |
| Aprendizado de máquina | Jupyter, `scikit-learn`, MLflow | Exploração e comparação de modelos com rastreamento reproduzível de experimentos. | Planejado; não está nas dependências |
| Documentação | MkDocs Material | Site estático versionado com validação de links no build. | Em uso |
| Automação | `just` + `uv` | Comandos canônicos e ambiente reproduzível a partir do `uv.lock`. | Em uso |

O racional da stack e das alternativas está no [registro de decisões tecnológicas](stackTecnologica.md). O plano reserva o ADR 0004 para ingestão/CDC e Delta Lake versus Iceberg.

## Requisitos não funcionais

| Requisito | Valor |
|---|---|
| Latência | < 300 ms nas telas (perguntas 1, 4 e 5); < 5 s nos relatórios (2 e 3) |
| Consistência | A, C e I obrigatórias ao aplicar reajuste; leitura analítica tolera dado de segundos atrás |
| Durabilidade | Obrigatória na carga: reingerir ~2,2 GB do SIDRA não é aceitável |
| Disponibilidade | Média: ferramenta de planejamento, não caixa de loja |
| Idempotência | As cargas implementadas são reexecutáveis por janela e usam chaves/hash para evitar duplicatas; a estratégia varia entre cada tabela Bronze e os carregadores legados |
| Concorrência no DuckDB | Os processos de carga são serializados por limitação de escritor. Publicação da Gold e leitura do painel ainda estão planejadas |
| Resiliência das origens | Falha de origem não corrompe o histórico já carregado; a carga termina com código diferente de zero e o modelo segue com o último dado conhecido |
| Acoplamento à origem | Fontes sem API (DIEESE) dependem do layout HTML: mudança de estrutura derruba a carga em vez de gravar dado errado, e a raw permite reprocessar offline |
| LGPD | Nenhuma fonte pública contém dado pessoal; CNPJ de lojista MEI é tratado como dado pessoal |

## ADRs

- [ADR 0001 — origem insert-only e dimensão de vigência](../arquitetura.md) (implementação parcial; histórico de nomes pendente).
- [ADR 0002 — um único arquivo DuckDB](../adr/0002-duckdb-unico.md) (adotado e em uso).
- [ADR 0003 — calendário civil para séries diárias do BCB](../adr/0003-bcb-macro.md) (implementado nos carregadores legados; migração para Silver pendente).
- [Plano do ADR 0004 — mecanismo de ingestão, CDC e formato Bronze](../pipeline/preparacao_bronze.md#42-e2-tarefas-comuns) (decisão pendente).
- [Registro de decisões tecnológicas](stackTecnologica.md) (stack atual e propostas futuras, sem substituir os ADRs do projeto).
