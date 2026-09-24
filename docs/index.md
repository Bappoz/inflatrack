# InflaTrack

Plataforma de dados que responde ao pequeno e médio lojista **quanto a inflação do setor dele subiu e qual reajuste ele precisa aplicar para não perder margem**.

Projeto Integrado da disciplina **Banco de Dados 2** — Engenharia de Software, FCTE/UnB. Squad Tio IPCA.

---

## Pergunta de Gestão

> *Dado o setor, a praça e o período, qual foi a inflação acumulada dos produtos que este lojista vende — e qual o reajuste mínimo para preservar a margem?*

A caracterização completa da carga de trabalho e o detalhamento das 5 perguntas derivadas estão documentados em [Caracterização da Carga](carga.md).

---

## Subir do Zero

### Requisitos

- **Docker Compose v2**
- **Python 3.12+** ou [uv](https://docs.astral.sh/uv/)
- [just](https://just.systems)

### Execução Rápida

```bash
git clone https://github.com/Bappoz/inflatrack.git && cd inflatrack
cp .env.example .env
just reset          # sobe o Postgres e aplica migrations/0001..0003 em ordem
just seed-amostra   # 3 meses do IPCA — confere que a ingestão funciona
```

Para carregar a série histórica inteira (jul/2006 a jul/2026, ~4,7 milhões de linhas):

```bash
just seed
just verificar-carga
```

!!! tip "Comandos Canônicos"
    O `justfile` é a fonte canônica dos comandos do projeto. Execute `just --list` para visualizar todas as receitas disponíveis.

---

## Fontes de Dados (SIDRA/IBGE)

Todas as séries temporais são obtidas diretamente da API do SIDRA/IBGE (`apisidra.ibge.gov.br`):

| Agregado | Índice | Período | Volume (Linhas) | Observação |
|---|---|---|---|---|
| [2938](https://sidra.ibge.gov.br/Tabela/2938) | IPCA | jul/2006 – dez/2011 | ~798 mil | Apenas 12 localidades; sem acumulado 12m |
| [1419](https://sidra.ibge.gov.br/Tabela/1419) | IPCA | jan/2012 – dez/2019 | ~2,19 mi | 464 categorias (POF 2008-2009) |
| [7060](https://sidra.ibge.gov.br/Tabela/7060) | IPCA | jan/2020 – | ~1,71 mi | 457 categorias (POF 2017-2018) |
| [7063](https://sidra.ibge.gov.br/Tabela/7063) | INPC | jan/2020 – | ~1,7 mi | Famílias de 1 a 5 salários mínimos |
| [1737](https://sidra.ibge.gov.br/Tabela/1737) | IPCA | dez/1979 – | 560 pontos | Número-índice geral Brasil (base dez/1993 = 100) |

---

## Arquitetura e Decisões

Para entender os padrões adotados no projeto:

- Consulte o [ADR 0001 — Modelagem do Sistema de Origem](adr/0001-modelagem-do-sistema-de-origem.md) sobre o padrão insert-only e cesta com vigência.
- Consulte o [Diário de Bordo](diario/index.md) para acompanhar as atualizações semanais da Squad.
