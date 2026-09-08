# Caracterização da carga de trabalho

Passo 1 do [Método de Decisão](https://unb-bd2.github.io/PlanoEnsino/adr/).
Números medidos em **2026-09-08** contra a API do SIDRA. Onde há extrapolação,
está dito.

## Volume

Medido: uma requisição por agregado, contando linhas com valor (descartando os
marcadores `...`, `..`, `-` e `X`). O total por agregado é **extrapolação** —
linhas do mês amostrado × número de meses publicados.

| Agregado | Período | Meses | Localidades | Categorias | Linhas/mês (medido) | Total (extrapolado) |
|---|---|---|---|---|---|---|
| 2938 | jul/2006 – dez/2011 | 66 | 12 | 465 | 12.093 | ~798 mil |
| 1419 | jan/2012 – dez/2019 | 96 | 17 | 464 | 22.784 | ~2,19 mi |
| 7060 | jan/2020 – jul/2026 | 79 | 17 | 457 | 21.620 | ~1,71 mi |
| 7063 (INPC) | jan/2020 – jul/2026 | 79 | 17 | 447 | ~21 mil | ~1,7 mi |
| 1737 (nº-índice) | dez/1979 – jul/2026 | 560 | 1 | — | — | 3.337 valores |

**~4,7 milhões de linhas** só de IPCA; ~6,4 milhões com o INPC. Toda a demais
referência (fontes, variáveis, localidades, cesta) soma menos de 2.500 linhas.

Estimativa em disco no PostgreSQL: **700 MB a 1 GB com índices** — estimativa
por largura média de linha, ainda não medida em banco populado.

## Taxa de escrita

- **Carga histórica:** um evento, ~4,7 milhões de inserções, reexecutável.
- **Regime:** ~21.620 linhas/mês por índice, numa única janela. O IBGE divulga o
  IPCA entre o **dia 9 e o dia 12** do mês seguinte — datas exatas em
  `servicodados.ibge.gov.br/api/v3/calendario` (11/09, 09/10, 12/11 e 11/12/2026).
  O agendamento deve consultar o calendário, não chutar um dia fixo.
- **Escrita transacional:** aplicar um reajuste. Volume baixíssimo, mas é a
  única escrita que exige atomicidade (linha em `reajuste` + leitura consistente
  do preço corrente na mesma transação).

## Taxa de leitura e padrão de acesso

| # | Consulta | Frequência | Tipo | Acesso |
|---|---|---|---|---|
| 1 | Inflação acumulada do meu setor em 12 meses | ~5/lojista/dia | pontual | filtro por (subitem, localidade, variável 2265), 1 linha |
| 2 | Meses do ano com maior pico histórico | ~1/lojista/dia | agregada | `GROUP BY` mês-do-ano sobre ~240 observações |
| 3 | Impacto no poder de compra desde 2006 | <1/lojista/dia | agregada | produto acumulado de 241 variações, ou razão de dois números-índice |
| 4 | Inflação geral × da minha região em 5 anos | ~1/lojista/dia | agregada | autojunção da fato, Brasil × praça |
| 5 | Reajuste mínimo para não perder margem | ~10/lojista/dia | pontual + escrita | junta `produto` com `observacao` pela FK do subitem |

Leitura domina: estimados 95%+ das operações. O índice
`observacao_consulta_idx (codigo_classificacao, codigo_localidade, codigo_variavel, mes_referencia desc)`
cobre 1, 4 e 5 diretamente.

A pergunta 3 tem dois caminhos e a diferença importa: encadear 241 variações
mensais (`exp(sum(ln(1+v/100)))`) funciona em qualquer granularidade mas acumula
erro; dividir dois números-índice do agregado 1737 é exato, mas só existe para o
índice geral no Brasil. Medido: `7657,73 / 2579,28 − 1 = **196,9%**` de inflação
acumulada entre jul/2006 e jul/2026 — R$ 1,00 de 2006 compra R$ 0,337 hoje.

## Latência tolerada

| Consulta | Alvo | Por quê |
|---|---|---|
| 1, 4, 5 | < 300 ms | São telas; o lojista espera resposta imediata |
| 2, 3 | < 5 s | São relatórios de planejamento, abertos deliberadamente |
| Carga mensal | horas | Dado mensal; uma hora de atraso não muda decisão nenhuma |

## Sazonalidade

Do lado da origem: nenhuma — uma divulgação por mês, sempre do mesmo tamanho.
Do lado do uso: concentração esperada logo após cada divulgação do IBGE e na
virada de ano, quando contratos e tabelas de preço são reajustados. Não medido —
não há usuário ainda.

## Restrições que a origem impõe

- **Teto de 50.000 valores por requisição.** Um mês do 7060 são 31.076 e passa;
  dois são 62.152 e devolvem HTTP 400. Paginação mensal é imposição, não escolha.
- **Custo de rede da carga histórica:** ~10,4 MB e 11–25 s por mês no formato
  padrão. Com `/f/c/h/n` (só códigos, sem cabeçalho) cai para 4,4 MB e ~9 s.
  Total baixado: ~2,2 GB no formato padrão, ~950 MB no compacto.
- **gzip na camada crua reduz 18×** (10,4 MB → 0,6 MB), medido.
- **Esquema heterogêneo:** o agregado 2938 não publica a variação acumulada em
  12 meses e cobre 12 localidades em vez de 17. Ingerir com o mesmo código sem
  tratar o caso produz série truncada sem erro.
- **A cesta muda de estrutura.** 43 subitens renomeados com código estável, 111
  removidos e 103 acrescentados entre 2006 e 2026.

## Consistência exigida

- Escrita de reajuste: atômica e isolada (A, C, I). Durável para não perder
  histórico de decisão do lojista.
- Leitura analítica: dado de segundos atrás é aceitável — não há requisito de
  ler a própria escrita nas perguntas 2 e 3.
- Carga: durável. Reingerir 2,2 GB por perda de dado não é aceitável.
