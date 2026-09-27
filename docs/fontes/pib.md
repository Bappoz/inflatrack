# PIB e Setores (SIDRA 1846)

Este documento registra as características arquiteturais e de negócio para a fonte de indicadores macroeconômicos, extraída da tabela [1846](https://sidra.ibge.gov.br/tabela/1846) do SIDRA/IBGE — *Valores a preços correntes* das Contas Nacionais Trimestrais.

É a contraparte do [IPCA/INPC](sidra.md): enquanto aquela fonte mede **quanto** o preço subiu, esta ajuda a explicar **por que** — custo na origem (agropecuária), custo de energia, frete, carga tributária, demanda das famílias e pressão do câmbio.

## Séries coletadas

Todas obtidas pela mesma API do SIDRA (`apisidra.ibge.gov.br`), variável 585, classificação `c11255`. As 23 categorias da tabela são baixadas — custam a mesma requisição —, mas 12 formam o **núcleo**, o recorte com efeito mais direto sobre o preço na prateleira do lojista.

| Código | Categoria | Grupo | Núcleo | Por que importa ao lojista |
|---|---|---|---|---|
| 90687 | Agropecuária — total | atividade | ✅ | Custo do alimento na origem |
| 90695 | Eletricidade e gás, água, esgoto, resíduos | atividade | ✅ | Energia embutida em todo produto |
| 90696 | Serviços — total | atividade | ✅ | Maior peso no IPCA de serviços |
| 90697 | Comércio | atividade | ✅ | A margem do próprio lojista |
| 90698 | Transporte, armazenagem e correio | atividade | ✅ | Frete até a prateleira |
| 90700 | Atividades financeiras e de seguros | atividade | ✅ | Custo do capital de giro |
| 90706 | Impostos líquidos sobre produtos | agregado | ✅ | Carga tributária sobre o preço final |
| 90707 | PIB a preços de mercado | agregado | ✅ | Denominador de tudo |
| 93404 | Despesa de consumo das famílias | demanda | ✅ | A demanda que puxa o preço |
| 93405 | Despesa de consumo da administração pública | demanda | ✅ | Demanda autônoma |
| 93407 | Exportação de bens e serviços | demanda | ✅ | Concorre com o abastecimento interno |
| 93408 | Importação de bens e serviços (-) | demanda | ✅ | Repasse do câmbio |
| 90691 | Indústria — total | atividade | — | |
| 90692 | Indústrias extrativas | atividade | — | |
| 90693 | Indústrias de transformação | atividade | — | |
| 90694 | Construção | atividade | — | |
| 90699 | Informação e comunicação | atividade | — | |
| 90701 | Outras atividades de serviços | atividade | — | |
| 90702 | Atividades imobiliárias | atividade | — | |
| 90703 | Administração, saúde e educação públicas | atividade | — | |
| 90705 | Valor adicionado a preços básicos | agregado | — | |
| 93406 | Formação bruta de capital fixo | demanda | — | |
| 102880 | Variação de estoque | demanda | — | |

O campo **grupo** existe porque as três famílias **não se somam entre si**: `atividade` é o valor adicionado pela ótica da produção, `demanda` é a ótica da despesa, e `agregado` são os totais. Somar as 23 linhas de um trimestre dá um número sem significado econômico.

---

## 1. Fonte de Origem

| Atributo | Resposta |
| :--- | :--- |
| **Nome da fonte** | SIDRA/IBGE — tabela 1846, Contas Nacionais Trimestrais (valores a preços correntes) |
| **Tipo** *(usuário / sistema / interna / terceiro)* | Terceiro |
| **Quem ou o que gera** | IBGE, Coordenação de Contas Nacionais. A estatística é compilada a partir de pesquisas do próprio IBGE (PIM, PMC, PMS, PAM), da balança comercial (MDIC), de registros administrativos e do Banco Central |
| **O que essa fonte contém** | Série trimestral, desde 1996T1, do PIB a preços de mercado, do valor adicionado por atividade (agropecuária, indústria, comércio, transporte, eletricidade e gás, serviços, atividades financeiras) e dos componentes da demanda (consumo das famílias e da administração pública, investimento, exportação e importação). Em milhões de reais correntes, só para o Brasil |
| **Formato em que chega** *(JSON, CSV, formulário, API...)* | JSON (API REST, `apisidra.ibge.gov.br`), no formato compacto `/f/c/h/n` — só códigos, sem nomes e sem cabeçalho. Os nomes vêm de uma chamada separada ao endpoint de metadados |
| **Volume estimado** *(por dia ou por mês)* | **Por divulgação:** 23 valores novos (1 trimestre × 23 categorias) mais a revisão de toda a série. **Por ano:** 92 registros e ~7,4 KB em disco (759 B no `.json.gz`, 6,7 KB no `.parquet`). **Base histórica completa** (1996T1–2026T2): 2.806 registros, 22,5 KB brutos e 202 KB em Parquet |
| **Frequência de chegada** *(tempo real / horária / diária / eventual)* | Trimestral, com ~60 dias de defasagem — o 2T/2026 foi publicado no início de setembro. Na prática é **eventual**: quatro divulgações por ano, em datas do calendário do IBGE |
| **Vazão** *(alta / média / baixa)* | Baixa. É a menor fonte do projeto: 2.806 linhas para 30 anos de história, contra ~6,4 milhões do IPCA/INPC |
| **Pureza** *(alta / média / baixa)* | **Alta.** Nos 2.806 valores baixados não houve um único marcador de ausência (`...`, `..`, `-`, `X`) e nenhum registro descartado. Sem buracos de calendário, diferente das séries diárias de [commodities](commodities.md). A ressalva não é de sujeira, e sim de semântica: são valores **correntes**, que misturam variação de preço e de quantidade |
| **Previsibilidade do formato** *(alta / média / baixa)* | Alta. Schema estável do SIDRA (`V`, `D1C`…`D4C`), o mesmo já usado na ingestão do IPCA. A única diferença é o período vir como `AAAATT` em vez de `AAAAMM` |
| **Contém dado pessoal?** *(sim / não)* | Não. Agregados macroeconômicos nacionais; nenhuma pessoa é identificável |
| **Base legal LGPD** *(se contém dado pessoal)* | Não se aplica. Dado público, sob os [termos de uso do IBGE](https://www.ibge.gov.br/acesso-informacao/institucional/politica-de-privacidade.html) |
| **Retenção** *(por quanto tempo guardar)* | Permanente. A série longa é o ativo: 30 anos cobrem o Plano Real maduro, a crise de 2008, a recessão de 2015-16 e a pandemia — os regimes que o modelo precisa ter visto. O custo de guardar tudo é de 202 KB |
| **O que quebra se essa fonte falhar** | As views `vw_pib_setor_trimestral`, `vw_pib_nucleo` e `vw_features_pib_trimestral` congelam no último trimestre carregado. O modelo perde a leitura macro do trimestre corrente e passa a explicar o movimento do preço com contexto defasado. **Não há quebra de integridade**: a carga é em lote, idempotente, e as tabelas `pib_*` são independentes das do IPCA (PostgreSQL) e das de commodities (mesmo DuckDB, outro prefixo) |

---

## 2. Conjunto de Dados / Armazenamento

| Atributo | Resposta |
| :--- | :--- |
| **Conjunto de dados** | Contas Nacionais Trimestrais — PIB e setores (Raw / Silver / Gold) |
| **Fonte de origem** *(nº da aba 1)* | SIDRA/IBGE — tabela 1846 |
| **Formato atual** | `.json.gz` (raw, um por ano) transformado em `.parquet` (um por ano) e carregado na base embutida `DuckDB`, em `pib_setor` e `pib_valor` |
| **Texto ou binário** | Binário nas duas camadas persistidas (gzip e Parquet). A origem chega como texto JSON e é comprimida antes de tocar o disco |
| **Orientação** *(linha / coluna / não se aplica)* | Linha na tabela física `pib_valor` (formato longo), com leitura transposta em coluna na view `vw_features_pib_trimestral` — mesmo desenho das commodities |
| **Tamanho estimado** *(em 1 ano)* | **~7,4 KB/ano** (759 B de `.json.gz` + 6,7 KB de `.parquet`). A base inteira, com 30 anos, ocupa 225 KB. O Parquet é 9× maior que o gzip porque o overhead de metadados do formato domina em arquivos de 92 linhas — irrelevante nesta escala, mas é o motivo de o número parecer invertido |
| **Como é lido** *(registro inteiro / poucas colunas / busca por chave)* | Os três padrões: recorte temporal completo da série (treino), busca por chave `(codigo_setor, data_referencia)` (uma série isolada) e poucas colunas via `vw_features_pib_trimestral` (matriz de features) |
| **Frequência de leitura** | Média-alta. Baixa contra a origem (4 coletas por ano); alta contra o armazenamento, nos notebooks de treino e backtesting, onde é lida junto com as commodities |
| **Formato proposto** | Manter: Parquet na camada bronze, em subpasta própria (`data/parquet/pib/`), e carga analítica embarcada no DuckDB, no **mesmo arquivo** das commodities |
| **Justificativa da escolha** | `pib_valor` segue o formato longo (*tall*), então mudar o recorte de categorias é editar `pib.NUCLEO` e recarregar, sem alterar schema. O DuckDB transpõe para o formato largo (*wide*) numa view, poupando pivotamento manual. **O arquivo único é a decisão central** ([ADR 0002](../adr/0002-duckdb-unico.md)): a pergunta do InflaTrack é multifonte — *"o comércio encareceu porque o frete subiu ou porque a agropecuária caiu?"* —, e num arquivo isso é `JOIN`, enquanto entre arquivos exigiria `ATTACH` em toda sessão e impediria FK entre as metades |
| **Ganho esperado** *(se houver troca)* | Não há troca de formato: a fonte já nasceu neste desenho, copiado do que funcionou nas commodities. O ganho é de integração — `vw_pib_setor_trimestral` e `commodity_cotacao` passam a ser joináveis numa consulta só, que é o cruzamento que o projeto precisa fazer e antes não fazia |

Detalhamento campo a campo das tabelas e views: [Dicionário de Dados — PIB e Setores](../dicionario/pib.md).

---

## 3. Carga de trabalho

### Taxa de escrita

- **Carga histórica:** um evento, 32 requisições (1 de metadados + 31 de valores, uma por ano de 1996 a 2026), concluído em ~9 s. Reexecutável a qualquer momento.
- **Regime:** 92 registros novos por ano, entregues em 4 lotes de 23. Entre divulgações, a escrita é zero.
- **Escrita real vs. custo de coleta:** a origem aceita filtro por período, então a carga incremental é honesta — `just pib-ingest 2026 2026` traz só o ano corrente em 1 requisição. Contrasta com a [Alpha Vantage](commodities.md), que devolve a série inteira a cada chamada e não permite janela.
- **Revisão da série:** cada divulgação revisa trimestres anteriores. Reprocessar o histórico é o caminho normal de atualização, não exceção — por isso o UPSERT por `(codigo_setor, data_referencia)`.
- **Escrita transacional:** nenhuma. Carga em lote, idempotente, sem exigência de atomicidade entre anos.

### Taxa de leitura e padrão de acesso

| # | Consulta | Frequência | Tipo | Acesso |
|---|---|---|---|---|
| 1 | Coleta na API do SIDRA | 4 rodadas/ano = 2 requisições cada (metadados + ano corrente) | lote | 1 requisição por ano de período |
| 2 | Série de um setor para treino/backtesting | alta, sob demanda (notebooks) | pontual | filtro por (`codigo_setor`, `data_referencia`) em `pib_valor` |
| 3 | Matriz de features macro para o modelo | alta, sob demanda (notebooks) | agregada | `SELECT *` em `vw_features_pib_trimestral` |
| 4 | Ranking de setores por aceleração no último trimestre | média, sob demanda | agregada | `vw_pib_nucleo` com `ORDER BY var_anual_pct` |
| 5 | Cruzamento macro × commodity (frete × Brent, alimento × café) | média, sob demanda | agregada | `JOIN` entre `vw_pib_setor_trimestral` e `commodity_cotacao` no mesmo DuckDB |

A leitura da **origem** é a mais baixa do projeto: 8 requisições por ano em regime. A leitura do **armazenamento** domina, mas é local, embarcada e não consome cota — não há cota a consumir.

---

## 4. Restrições que a origem impõe

- **O período é `AAAATT`, não `AAAAMM`.** `199603` é o 3º trimestre de 1996, não março. Reaproveitar `ingest.mes_para_data` daria março silenciosamente, sem erro nenhum. Por isso `pib.trimestre_para_data` rejeita `TT` fora de 1..4.
- **A API não precisa de paginação aqui.** Um ano inteiro são 4 × 23 = 92 valores, contra o teto de 50.000 valores por requisição — três ordens de grandeza de folga. A paginação anual é escolha de organização da camada crua, não imposição da origem como no [IPCA](sidra.md), onde um único mês do agregado 7060 já consome 31.076 dos 50.000.
- **Defasagem de ~60 dias.** O trimestre só existe na base dois meses depois de terminado. Qualquer leitura "do trimestre corrente" é, na verdade, do trimestre anterior — o modelo precisa tratar isso como *lag* estrutural, não como atraso de coleta.
- **A série é revisada a cada divulgação.** Um número já carregado pode mudar. A carga sobrescreve, o que é o comportamento certo aqui, mas é o **oposto** do IPCA, onde `observacao` é insert-only para preservar o valor com que a plataforma respondeu antes.
- **Só existe o nível Brasil (N1).** Não há recorte por praça nem por UF, diferente do IPCA, que cobre 17 localidades. O cruzamento regional tem de vir do outro lado.
- **Valores correntes misturam preço e quantidade.** A variação entre dois trimestres embute inflação **e** mudança de volume. Isolar preço exigiria o deflator implícito, o que depende da tabela de índices de volume da mesma pesquisa — ainda não ingerida.
- **Sem cota e sem chave de API.** O SIDRA é aberto e não exige autenticação, então não há o gargalo de 25 requisições/dia da [Alpha Vantage](commodities.md). O limite prático é de educação com o serviço público, não contratual.
