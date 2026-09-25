# Visão Geral da Arquitetura

O InflaTrack junta duas metades de natureza oposta:

| Metade | O que guarda | Volume | Escrita |
|---|---|---|---|
| **Referência pública** | Séries do IBGE (IPCA, INPC) e variáveis explicativas (commodities) | ~4,7 mi linhas de IPCA; ~6,4 mi com INPC | Lote, mensal (IBGE) ou diária (commodities) |
| **Transacional própria** | Lojista, produto e reajuste | Baixíssimo | Aplicar reajuste: a única escrita que exige transação |

A ponte entre as duas é a FK `produto.codigo_subitem_ipca`: é ela que permite responder "quanto a inflação do que eu vendo subiu".

## Stack

| Peça | Tecnologia | Papel |
|---|---|---|
| Banco principal | PostgreSQL 16.4 (Docker Compose, limite de 2 GB de memória) | Referência do IBGE + lado transacional |
| Camada crua do IPCA | Arquivos JSON gzip em `data/raw/` | Auditoria e reprocessamento sem chamar a API |
| Base analítica de commodities | DuckDB + Parquet em `data/` | Features para os modelos de previsão ([detalhes](../fontes/commodities.md)) |
| Ingestão | Python 3.12, `httpx`, `psycopg` | Clientes das APIs e carga ELT |
| Automação | `just` + `uv` | Comandos canônicos (`just --list`) |

## Requisitos não funcionais

| Requisito | Valor |
|---|---|
| Latência | < 300 ms nas telas (perguntas 1, 4 e 5); < 5 s nos relatórios (2 e 3) |
| Consistência | A, C e I obrigatórias ao aplicar reajuste; leitura analítica tolera dado de segundos atrás |
| Durabilidade | Obrigatória na carga: reingerir ~2,2 GB do SIDRA não é aceitável |
| Disponibilidade | Média: ferramenta de planejamento, não caixa de loja |
| LGPD | Dado do IBGE não é pessoal; CNPJ de lojista MEI é tratado como dado pessoal |

## Decisões

- [ADR 0001 — origem insert-only com a cesta do IPCA em dimensão de vigência](../arquitetura.md) (proposto; falta a medição).
