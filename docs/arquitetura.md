# 0001 — Modelar a origem como insert-only, com a cesta do IPCA em dimensão de vigência

- **Status:** implementação parcial; dimensão histórica pendente
- **Data:** 2026-09-08
- **Revisado em:** 2026-10-18
- **Decisores:** Squad InflaTrack; aprovação formal da dimensão histórica pendente

> **Estado deste ADR.** O histórico de valores está implementado como append-only
> no PostgreSQL. A dimensão de nomes com vigência ainda não está implementada:
> o esquema e o ingestor atual substituem o nome anterior. Portanto, a decisão
> completa continua pendente e esta página não afirma que a cesta histórica já
> pode ser consultada com fidelidade.

## Contexto

O InflaTrack responde ao pequeno lojista quanto a inflação do setor dele subiu e
qual reajuste aplicar. A origem tem duas metades de natureza oposta:

1. **Referência pública** — a série do IPCA/INPC publicada pelo IBGE. ~4,7
   milhões de linhas, mensal, imutável em regime mas **revisável**: o IBGE
   republica valor de mês já divulgado.
2. **Transacional própria** — lojista, produto e reajuste. Volume baixíssimo,
   integridade alta, é a única escrita frequente do sistema.

A carga está caracterizada com número em [Fonte SIDRA/IBGE](fontes/sidra.md). Os três
fatos da origem que forçam a mão:

- A cesta **muda de estrutura**. Entre jul/2006 e jul/2026 houve duas revisões
  (POF 2008-2009 e POF 2017-2018): **43 subitens mudaram de nome mantendo o
  mesmo código** (`1111004` "Leite pasteurizado" → "Leite longa vida";
  `3202028` "Microcomputador" → "Computador pessoal"; `9101008` "Telefone
  celular" → "Plano de telefonia móvel"), **111 saíram** e **103 entraram**.
- O IBGE **revisa valor já publicado**. Se a plataforma sugeriu um reajuste com
  base no número antigo, precisa conseguir dizer com que número sugeriu.
- O esquema não é uniforme entre agregados: 2938 não tem a variação acumulada em
  12 meses e cobre 12 localidades em vez de 17.

## Restrições não funcionais

| Restrição | Valor |
|---|---|
| Consistência | A, C, I obrigatórias ao aplicar reajuste; leitura analítica tolera dado defasado |
| Latência | < 300 ms nas telas (perguntas 1, 4, 5); < 5 s nos relatórios (2, 3) |
| Disponibilidade | Média — ferramenta de planejamento, não caixa de loja |
| Custo | Zero: exigência da disciplina é stack livre em Docker Compose |
| Legal | Dado do IBGE é agregado, sem pessoa identificável. CNPJ de lojista MEI se confunde com pessoa física → tratar como dado pessoal (LGPD) |
| Competência da Squad | SQL e PostgreSQL, sim. Nenhum integrante operou banco de documento ou de série temporal em produção — restrição real, e é para estar escrita |
| Origem | Teto de 50.000 valores/requisição; ~2,2 GB na carga histórica |

## Padrões de acesso previstos

As cinco consultas, com frequência e tipo, estão em
[Fonte SIDRA/IBGE](fontes/sidra.md#taxa-de-leitura-e-padrao-de-acesso). O resumo que
decide: **leitura domina (95%+)**, o filtro quase sempre é
`(subitem, localidade, variável, mês)`, e a única consulta que junta as duas
metades do sistema é a 5 — produto do lojista × observação do IBGE, pela FK do
subitem.

## Alternativas consideradas

### A. Opção nula — não ter banco; consultar a API do SIDRA a cada pergunta

Viável no papel: a fonte é pública, tem API aberta e o dado já vem calculado.
Elimina esquema, migration, carga e operação de banco.

**Medido, e é o que a elimina:** a API limita 50.000 valores por requisição e
leva 11–25 s por mês de dado. A pergunta 3 precisa de 241 meses — ~56 min de
espera por consulta, sem contar o teto de requisições. A pergunta 5 não é
respondível de jeito nenhum: exige juntar dado do IBGE com o catálogo de
produtos do lojista, que só existe do nosso lado.

### B. CRUD sobrescrevendo — uma linha por (classificação, localidade, variável, mês), atualizada quando o IBGE revisa

Esquema menor, ~4,7 milhões de linhas fixas, sem crescimento. Consulta mais
simples: não precisa desempatar versões.

Cobra o histórico de decisão: depois de um `UPDATE`, não há como responder "com
que número a plataforma sugeriu aquele reajuste em março". Para um produto cuja
razão de existir é justificar reajuste, isso é perder a prova.

### C. Insert-only com cesta em dimensão de vigência _(proposta)_

`observacao` só recebe `INSERT`; revisão do IBGE entra como linha nova. O nome
da categoria mora em `classificacao_versao` com `vigencia_inicio`/`vigencia_fim`,
separado da chave natural estável em `classificacao`.

Cobra volume (cada revisão duplica as linhas do mês afetado) e cobra uma junção
a mais em toda consulta que precise do nome. Dá de graça o histórico e a
continuidade da série sob renomeação — e é o mesmo padrão que a E3 vai exigir
como dimensão de variação lenta.

## Medição

O comportamento de gravação dos valores foi verificado na carga histórica. A
comparação de desempenho entre B e C continua pendente; deve usar o banco
populado e os scripts de consulta versionados:

1. `EXPLAIN (ANALYZE, BUFFERS)` das cinco consultas sobre B e sobre C, com a
   série completa carregada.
2. Tamanho em disco de cada modelagem, com e sem os índices.
3. Custo da junção com `classificacao_versao` na pergunta 1 (a mais frequente).

| Alternativa | Latência p95 pergunta 1 | Latência pergunta 3 | Disco | Responde a pergunta 5? |
|---|---|---|---|---|
| A. Opção nula | — | ~56 min (medido) | 0 | Não |
| B. CRUD | a medir | a medir | a medir | Sim |
| C. Insert-only | a medir | a medir | a medir | Sim |

## Decisão

A proposta é a **alternativa C**, porque uma revisão do IBGE não deve apagar o
valor que fundamentou uma sugestão anterior de reajuste. A escolha é por
auditabilidade e continuidade da série, não por uma medição de desempenho.

O estado real do código é parcial:

- `observacao` preserva valores distintos para a mesma chave e mês; uma
  reexecução do mesmo valor é idempotente.
- `classificacao_versao` é uma dimensão tipo 2 desde a E3 (migration `0004`):
  uma linha por vigência e, no máximo, uma aberta por `(codigo, id_fonte)`.
  `sincronizar_cesta()` fecha a versão aberta e abre outra quando o nome ou o
  pai mudam. Até a E2, uma renomeação apagava o nome anterior e sua vigência.

Assim, o histórico de valores é uma decisão já materializada; a modelagem de
vigência permanece proposta até que o esquema permita múltiplas versões e a
ingestão feche a vigência anterior em vez de sobrescrevê-la. A avaliação de
latência e disco também continua pendente e não deve ser apresentada como
resultado medido.

## Consequências

**O que ganhamos:** preservação dos valores publicados em cada carga e
idempotência quando o mesmo conteúdo é ingerido novamente. A FK mantém a
classificação referenciada por produtos.

**O que perdemos:** até a dimensão tipo 2 ser concluída, não é possível
reconstruir pelo banco o nome que o IBGE usava quando uma observação antiga foi
carregada. Quando concluída, consultas que precisem do nome terão de filtrar a
versão válida para o período.

**O que se torna difícil de reverter:** consumidores que usem apenas o valor
mais recente deixarão de ver a revisão anterior; por isso relatórios de
auditoria precisam escolher explicitamente uma versão. Os valores anteriores
continuam preservados no fato.

## Gatilho de revisão

Revisar após a migration e a sincronização de cesta passarem a preservar duas
versões para um mesmo `(codigo, id_fonte)`, com períodos sem sobreposição. Nesse
ponto, medir `EXPLAIN (ANALYZE, BUFFERS)` das cinco consultas e o espaço em disco
com a carga completa. Reabrir a decisão se a consulta 1 exceder 300 ms p95 ou
qualquer relatório exceder 5 s, os limites definidos para o produto.
