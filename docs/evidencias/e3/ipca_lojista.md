# Evidência E3 — IPCA, lojista e Gold

Executado em **2026-10-31** (Linux, Python 3.12, dbt-core 1.12.6, dbt-duckdb 1.11.1, DuckDB 1.5.5, `postgres:16.4-alpine`), do zero: Postgres em volume novo, DuckDB novo e Delta do CDC novo. A Bronze do IPCA é a coletada em 2026-10-11 ([Evidência E2](../e2/ipca.md)), mais os metadados baixados nesta data.

!!! warning "O que é real e o que é demonstração"
    Os dados do **IPCA/INPC são reais**, do SIDRA. Os dados do **lojista são fictícios**, criados por `just simular-cdc`: não existe lojista real no projeto. As contas são reais, os preços não.

## Do zero até a vitrine

```bash
just up                       # Postgres com wal_level=logical e migrations 0001..0005
just ipca-load                # Delta -> bronze.ipca_observacao e bronze.ipca_metadados
just simular-cdc              # mudanças reais no Postgres -> CDC -> Delta
just transacional-load        # Delta -> bronze.transacional_mudanca
uv run dbt build --select +fct_inflacao_mensal +fct_reajuste_lojista dim_localidade dim_calendario
just serie                    # Gold -> schema serie do Postgres
just explain-serie            # planos em docs/evidencias/e3/
```

| Etapa | Resultado |
|---|---|
| `load_ipca` | 9.116.436 observações e 1.833 versões de categoria. Na 2ª execução, 0 linhas novas |
| `dbt build` (modelos e testes desta trilha) | 114 de 114 passaram, em 33 s |
| Cópia para `serie` | 6 tabelas em cerca de 44 s, das quais 1.662.314 linhas em `fct_inflacao_mensal` |

## Conferência da Gold com o que o IBGE publica {#ipca}

Antes de confiar na fato, cada número foi comparado com a fonte ou com uma conta independente:

| O que foi conferido | Resultado | Teste que mantém isso |
|---|---|---|
| Índice geral, Brasil, set/2026, acumulado em 12 meses | 4,58%, igual ao publicado pelo IBGE (variável 2265) | |
| Acumulado **calculado** contra o **publicado** (geral e grupos, Brasil, desde 2013) | Diferença máxima de 0,0326 p.p., efeito do arredondamento das mensais | `assert_ipca_acum12m_calculado_bate_publicado` |
| Soma dos pesos dos grupos, em toda localidade e todo mês | Sempre a menos de 0,5 p.p. de 100 | `assert_ipca_pesos_somam_100` |
| Meses do índice geral do Brasil | 562 meses contínuos, de dez/1979 a set/2026 | `assert_ipca_serie_sem_mes_faltando` |
| Variação mensal do índice geral desde jul/2006 | Entre -2,12% e 2,54% | `assert_ipca_variacao_mensal_sem_salto_absurdo` |
| Número-índice de dez/1979 no Postgres | `0.0000000076183`, exato (antes da migration `0004`, arredondava para zero) | `tests/integration` |

### O que a conferência ensinou

- **As localidades entraram aos poucos.** A suposição inicial era "12 até 2011 e 17 depois", e o teste falhou em 76 meses. O dado real: 12 localidades desde jul/2006, Campo Grande e Grande Vitória em jan/2014, Aracaju, Rio Branco e São Luís em mai/2018. Antes de entrar, a localidade aparece na resposta do SIDRA só com marcador. O teste passou a exigir continuidade em cada localidade, sem número fixo.
- **Salto grande em subitem é real.** A maior variação mensal é de 358,36% (`5102015`, Porto Alegre, jun/2024). Por isso o limite de 5% vale só para o índice geral; no subitem, é de 500%.
- **O peso muda todo mês.** O IBGE o atualiza com os preços relativos (Alimentação e bebidas, Brasil: 23,1237 em jan/2012 e 23,1948 em fev/2012). Um SCD2 sobre o peso mensal abriria uma versão por mês e por localidade. A mudança de verdade é a troca de estrutura: de 24,5671 em dez/2019 para 19,3483 em jan/2020.

## SCD tipo 2 da cesta {#cesta}

`gold.dim_cesta_ipca_scd2` abre versão quando a estrutura (POF) muda ou quando o nome ou o pai mudam. São 1.834 versões. O peso mensal fica na fato; a dimensão guarda os pesos do início e do fim de cada versão.

Categoria `1`, IPCA:

| Nome | Estrutura | Início | Fim (não entra) | Peso no início | Peso no fim |
|---|---|---|---|---|---|
| Alimentação e bebidas | POF 2002-2003 | 2006-07 | 2012-01 | 20,2879 | 23,4584 |
| Alimentação e bebidas | POF 2008-2009 | 2012-01 | 2020-01 | 23,1237 | 24,5671 |
| Alimentação e bebidas | POF 2017-2018 | 2020-01 | (aberta) | 19,3483 | 21,5090 |

O histórico de nomes fica preservado: `1111004` era "Leite pasteurizado" na POF 2002-2003 e virou "Leite longa vida" em 2012. No IPCA, 44 códigos têm mais de um nome ao longo das versões.

No Postgres, `classificacao_versao` passou a seguir a mesma regra: renomear fecha a versão aberta e abre outra, em vez de sobrescrever (`ipca.sincronizar_cesta`, com teste de integração). A migration `0004` permite várias versões por código e garante, por índice único parcial, que só uma fique aberta.

## CDC {#cdc}

`just simular-cdc` faz mudanças reais no Postgres e captura entre um passo e outro:

| Passo | O que acontece | Mudanças lidas | Novas na Bronze |
|---|---|---|---|
| 1. Cadastro | Lojista, 3 produtos e 3 vendas | 7 | 7 |
| 2. Mudanças | Custo, reajuste, renomeação e exclusão de produto | 4 | 4 |
| 3a. Queda | Um `UPDATE`; grava no Delta e "cai" antes de avançar o slot | 1 | 1 |
| 3b. Retomada | A captura seguinte lê o mesmo evento | 1 | **0** |
| 4. Atraso | Reajuste de janeiro registrado depois do de março | 1 | 1 |

Ao fim, a demonstração procura o CNPJ em todas as linhas da Bronze e falha se o encontrar. Decisão e alternativas no [ADR de ingestão](../../adr/cdc-vs-lote.md).

### O evento atrasado entra na posição certa

O reajuste de 05/01 foi capturado **depois** do de 10/03, com LSN maior. Na `gold.dim_produto_preco_scd2`, o histórico do "Arroz 5kg" sai na ordem do negócio:

| Versão | Preço | Custo | Evento | Início | Fim (não entra) |
|---|---|---|---|---|---|
| 1 | 25,00 | 18,00 | cadastro | 2025-09-15 | 2026-01-05 |
| 2 | **25,80** | 18,00 | reajuste (o atrasado) | 2026-01-05 | 2026-02-20 |
| 3 | 25,80 | 19,00 | custo | 2026-02-20 | 2026-03-10 |
| 4 | 26,50 | 19,00 | reajuste | 2026-03-10 | (aberta) |

O `UPDATE` do passo 3a não muda nenhum atributo da dimensão e, corretamente, não abre versão. O produto excluído fica com a última versão fechada na hora da exclusão, sem apagar o histórico.

## Fato do lojista: a pergunta 5 {#fato-lojista}

`gold.fct_reajuste_lojista`, uma linha por produto x mês, para o Arroz 5kg (fictício), comparado com o subitem Arroz em Brasília:

| Mês | Preço | IPCA do mês | Último mês do IBGE | IPCA 12m | Defasagem | Reajuste mínimo |
|---|---|---|---|---|---|---|
| 2026-08 | 26,50 | 0,47% | 2026-08 | -15,03% | -19,84% | 0% |
| 2026-09 | 26,50 | 4,90% | 2026-09 | -10,87% | -15,91% | 0% |
| 2026-10 | 26,50 | não publicado | 2026-09 | -10,87% | -15,91% | 0% |

- **Conta independente:** o IPCA de 12 meses da fato do lojista em set/2026 (-10,8650%) é a mesma janela que o IBGE publica para Arroz em Brasília (-10,86%).
- **Leitura:** o preço subiu 6% enquanto o subitem caiu, então o lojista está à frente da inflação: defasagem negativa e nenhum reajuste necessário. Num subitem em alta, a defasagem seria positiva.
- **Out/2026 ainda não foi publicado:** a janela fica parada em setembro (`mes_ipca_referencia`). Antes da correção, a primeira versão do modelo perdia o mês mais antigo sem ganhar o novo e mostrava -5,65%, um número errado justamente no mês mais consultado.

## Migration em volume existente {#migracao}

As migrations `0004` e `0005` foram aplicadas a uma **cópia** do volume de desenvolvimento, com 5.992.897 linhas em `observacao`. A `0004` levou 52 s, porque `alter type` reescreve a tabela e os índices. A `0005`, 0,3 s. O volume original não foi tocado.

## Limitações

- **`fct_inflacao_mensal` ainda não tem as variáveis explicativas.** Dólar, Selic, clima e salário mínimo ainda não têm Silver neste branch. Elas se encontram com a fato por `mes_referencia`, via `dim_calendario`, e a Gold pura evita depender de modelo de colega que não existe.
- **Praça do lojista:** a comparação usa a praça atual para todo o histórico. Mudança de praça não abre versão.
- **Vigência da renomeação da cesta:** é aproximada pelo mês em que os metadados a mostraram, porque o IBGE não publica a data. A Bronze de metadados começou em 2026-10-31, e renomeações dentro de um mesmo agregado anteriores a isso não são recuperáveis.
- **`dbt build` completo nesta máquina:** há erro só nos testes de `bronze.pib_valor` e `bronze.commodities_cotacao`, porque a Bronze dessas fontes não existe aqui (a de commodities exige chave da Alpha Vantage). Excluindo essas duas trilhas, 127 de 127 passaram.
- **Acesso:** os papéis da `0005` não têm login, e `exportar_serie` ainda conecta com o usuário dono do banco. Privilégio mínimo de verdade e RLS são da E4.
