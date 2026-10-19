# 0002 — Um único arquivo DuckDB para todas as fontes analíticas

- **Status:** adotado; loaders existentes usam o arquivo único
- **Data:** 2026-09-25
- **Revisado em:** 2026-10-18
- **Decisores:** Squad InflaTrack

## Contexto

Com a entrada das Contas Nacionais Trimestrais ([SIDRA 1846](../fontes/pib.md))
ao lado das commodities da Alpha Vantage, a camada analítica passou a ter mais
de uma fonte. A pergunta que apareceu: **um DuckDB por fonte, ou um só?**

Números medidos em 2026-09-25:

| Fonte | Observações | Tamanho na camada servida |
|---|---|---|
| Commodities (Alpha Vantage) | 26.781 | 9 séries |
| Contas Nacionais (SIDRA 1846) | 2.806 | 23 setores |

Duas ordens de grandeza abaixo do que justificaria particionar por arquivo. O
transacional do lojista e o histórico do IPCA continuam no Postgres — este ADR
trata só da camada analítica.

## Alternativas

**A. Um arquivo por fonte** (`commodities.duckdb`, `pib.duckdb`).

- ✅ Isola falha de carga: corromper um não derruba o outro.
- ✅ Cada fonte tem seu ciclo de reprocessamento.
- ❌ Todo cruzamento exige `ATTACH` explícito **em cada sessão**. A consulta
  deixa de ser portátil: quem abrir o arquivo errado vê metade do mundo.
- ❌ Não há integridade referencial entre bancos anexados no DuckDB. `pib_valor`
  não poderia referenciar `pib_setor` se estivessem separados por fonte.
- ❌ Multiplica artefato: cada nova fonte vira mais um arquivo a versionar,
  distribuir e documentar.

**B. Um arquivo único, tabelas e views por fonte.** *(escolhida)*

- ✅ Cruzar fontes é `JOIN`, não `ATTACH`. E cruzar é o produto: *"o comércio
  encareceu porque o frete subiu, ou porque a agropecuária caiu?"* só se
  responde com PIB setorial e commodities na mesma consulta.
- ✅ FK real dentro de cada fonte (`pib_valor` → `pib_setor`).
- ✅ Um artefato para distribuir para a Squad.
- ⚠️ O isolamento passa a ser por **prefixo de tabela e por view**, não por
  arquivo. Exige disciplina de nomenclatura (`pib_*`, `commodity_*`).
- ⚠️ DuckDB permite um único processo escritor por arquivo. Com as cargas
  rodando em sequência (`just pib`, depois as commodities) isso não morde; se
  virarem paralelas, morde.

## Decisão

**Alternativa B.** O critério é o padrão de acesso, não o volume: a pergunta de
gestão do InflaTrack é intrinsecamente multifonte, e o custo de B aparece só num
volume que este projeto não tem.

Regras que tornam B sustentável:

1. **Prefixo por fonte** em toda tabela: `commodity_*`, `pib_*`.
2. **Separar os formatos e esquemas de Bronze por caminho.** A carga legada de
   commodities lê `data/parquet/*.parquet` e espera `(symbol,
   data_referencia, preco)`. Novas fontes ficam em caminhos próprios, como
   `data/parquet/pib/`; as fontes em Delta Lake também usam uma pasta por
   tabela. Não misturar esquemas no glob legado.
3. **Cargas em sequência**, nunca em paralelo, enquanto o escritor for único.

## Consequências

- Uma nova fonte analítica entra com: um `setup_duckdb_<fonte>.sql`, uma
  pasta de Bronze isolada, um módulo de ingestão e um módulo de carga. Nenhum
  arquivo novo de banco é criado.
- O arquivo compartilhado simplifica `JOIN`s entre fontes, mas também concentra
  risco de corrupção e exige serializar escritores. Se houver necessidade de
  alta disponibilidade, isolamento de falhas ou escritas concorrentes, este
  ADR deve ser revisto; volume de linhas sozinho não é o único gatilho.
