# IPCA/INPC

Todas as séries temporais são obtidas diretamente da API do SIDRA/IBGE (`apisidra.ibge.gov.br`):

| Agregado | Índice | Período | Volume (Linhas) | Observação |
|---|---|---|---|---|
| [2938](https://sidra.ibge.gov.br/Tabela/2938) | IPCA | jul/2006 – dez/2011 | ~798 mil | Apenas 12 localidades; sem acumulado 12m |
| [1419](https://sidra.ibge.gov.br/Tabela/1419) | IPCA | jan/2012 – dez/2019 | ~2,19 mi | 464 categorias (POF 2008-2009) |
| [7060](https://sidra.ibge.gov.br/Tabela/7060) | IPCA | jan/2020 – | ~1,71 mi | 457 categorias (POF 2017-2018) |
| [7063](https://sidra.ibge.gov.br/Tabela/7063) | INPC | jan/2020 – | ~1,7 mi | Famílias de 1 a 5 salários mínimos |
| [1737](https://sidra.ibge.gov.br/Tabela/1737) | IPCA | dez/1979 – | 560 pontos | Número-índice geral Brasil (base dez/1993 = 100) |

---

## 1. Fonte de Origem

| Atributo | Resposta |
| :--- | :--- |
| **Nome da fonte** | SIDRA/IBGE - API de valores (`apisidra.ibge.gov.br`) e API de metadados de agregados (`servicodados.ibge.gov.br/api/v3/agregados`) |
| **Tipo** *(usuário / sistema / interna / terceiro)* | Terceiro (órgão público oficial) |
| **Quem ou o que gera** | IBGE, a partir da pesquisa de preços que alimenta o IPCA e o INPC. Os índices são calculados e divulgados pelo próprio instituto; o projeto apenas consome. |
| **O que essa fonte contém** | Séries mensais de IPCA e INPC por categoria da cesta (grupo, subgrupo, item e subitem) e por localidade (Brasil, regiões metropolitanas e municípios, 17 no total), com variação mensal, variação acumulada em 12 meses e outras variáveis do agregado. Inclui também o número-índice geral do Brasil (agregado 1737) e os metadados (nomes e hierarquia das categorias). |
| **Formato em que chega** *(JSON, CSV, formulário, API...)* | JSON (via API REST), no formato compacto `/f/c/h/n` (só códigos, sem nomes e sem cabeçalho). Os nomes vêm do endpoint de metadados, chamado uma vez por agregado. |
| **Volume estimado** *(por dia ou por mês)* | Por mês: ~21,6 mil linhas por índice (medido no IPCA 7060), cerca de 43 mil somando IPCA e INPC. Por carga histórica (evento único): ~4,7 milhões de linhas de IPCA, ~6,4 milhões com o INPC. Em rede, ~4,4 MB por mês e por agregado no formato compacto (medido no 7060). |
| **Frequência de chegada** *(tempo real / horária / diária / eventual)* | Mensal. O IBGE divulga o IPCA entre os dias 9 e 12 do mês seguinte; as datas exatas ficam em `servicodados.ibge.gov.br/api/v3/calendario`. Os agregados 2938 e 1419 são históricos e não recebem mais dados; só 7060, 7063 e 1737 seguem em atualização. |
| **Vazão** *(alta / média / baixa)* | Baixa (uma janela por mês, com ~3 requisições de valores e 3 de metadados por rodada, uma por agregado ativo) |
| **Pureza** *(alta / média / baixa)* | Média (dado oficial e consistente, mas com marcadores de ausência (`...`, `..`, `-`, `X`) misturados aos valores; o `-` sozinho é ausente, enquanto `-0.67` é deflação real. O agregado 2938 não traz o acumulado em 12 meses e cobre 12 localidades em vez de 17, o que trunca a série sem erro se não for tratado) |
| **Previsibilidade do formato** *(alta / média / baixa)* | Média (o payload compacto tem chaves fixas (`D1C`, `D2C`, `D4C`, `V`), mas o esquema muda entre agregados e a cesta muda de estrutura: 43 subitens renomeados, 111 removidos e 103 acrescentados entre 2006 e 2026. O `D4C` traz o id interno do SIDRA, não o código natural da categoria, e exige tradução pelos metadados) |
| **Contém dado pessoal?** *(sim / não)* | Não (índices agregados por categoria e localidade, sem informação de indivíduos ou domicílios) |
| **Base legal LGPD** *(se contém dado pessoal)* | Não se aplica |
| **Retenção** *(por quanto tempo guardar)* | Permanente. A série é a base histórica do produto (acumulado desde 2006), e reingerir ~2,2 GB por perda de dado não é aceitável. A resposta crua é mantida em gzip (`data/raw/ipca-inpc/`, ~18× menor) para reprocessamento e auditoria. |
| **O que quebra se essa fonte falhar** | A atualização mensal dos índices: o produto passa a responder com base no último mês carregado, e o cálculo de inflação acumulada e de reajuste mínimo fica defasado. O histórico já carregado permanece íntegro, e a carga é idempotente, então basta reexecutar quando a API voltar. |

---

## 2. Conjunto de Dados / Armazenamento

O dado passa por duas camadas com natureza diferente (ELT: grava a resposta crua e só depois transforma dentro do banco), por isso cada resposta separa a **camada crua** do **banco relacional**.

!!! note "Estado atual"
    Descreve o que está implementado hoje (entrega 1): JSON gzip em disco + PostgreSQL 16. A migração da camada analítica para DuckDB/Parquet está em discussão e, quando decidida, atualiza esta seção.

| Atributo | Camada crua (`data/raw/ipca-inpc/`) | Banco relacional (tabela `observacao`) |
| :--- | :--- | :--- |
| **Conjunto de dados** | Resposta da API exatamente como veio, um arquivo por agregado e mês (`{agregado}-{AAAAMM}.json.gz`) | Observações de IPCA/INPC das 5 fontes unificadas numa série só |
| **Formato atual** | JSON compacto (`/f/c/h/n`) em gzip | Tabela PostgreSQL (heap); `valor numeric(16,7)`, `mes_referencia date` |
| **Texto ou binário** | Texto (comprimido) | Binário |
| **Orientação** | Linha | Linha |
| **Tamanho estimado** | 46 MB para os ~880 arquivos da carga histórica; ~0,6 MB por mês e agregado | ~4,7 mi linhas de IPCA (~6,4 mi com INPC) + ~260 mil/ano por índice. 700 MB a 1 GB com índices (**estimativa** por largura de linha, não medida) |
| **Como é lido** | Registro inteiro, uma vez, na carga ou em reprocessamento | Poucas colunas (`valor`, `mes_referencia`) filtradas por subitem + localidade + variável |
| **Frequência de leitura** | Quase nula — não é consultada | Alta — toda tela do lojista lê daqui |
| **Formato proposto** | Manter JSON gzip | Manter PostgreSQL na E1; réplica colunar (Parquet) para as consultas analíticas |
| **Justificativa da escolha** | Existe para reprocessar sem chamar a API e provar de onde veio o número. Converter destruiria a auditoria; gzip porque o JSON repete as chaves em cada objeto | O valor da consulta está no JOIN com a hierarquia da cesta e com o produto do lojista (FK do subitem). Colunar trocaria a escrita transacional barata por leitura analítica, que só as perguntas 2 e 3 precisam |
| **Ganho esperado** | 18× menos disco (10,4 MB → 0,6 MB por mês, medido) | Na E1, nenhuma troca de formato |

---

## 3. Carga de trabalho

### Taxa de escrita

- **Carga histórica:** um evento, reexecutável. São ~4,7 milhões de linhas de IPCA (~6,4 milhões com o INPC) em ~880 requisições de valores, uma por mês e por agregado (66 + 96 + 79 + 79 + 560), mais uma de metadados por agregado. As 320 primeiras são pesadas (~9 s cada no formato compacto); as 560 do agregado 1737 são leves, mas desnecessárias (ver restrições).
- **Regime:** uma janela por mês, logo após a divulgação do IBGE (dias 9 a 12). São ~21,6 mil linhas novas por índice, cerca de 43 mil com IPCA e INPC, mais uma linha do número-índice do 1737. Nada chega fora dessa janela.
- **Descarte na entrada:** a API devolve ~31 mil linhas por mês no 7060, e ~30% delas são marcadores de ausência que a carga descarta (medido em jul/2026: 9.456 de 31.076). O volume gravado é menor que o trafegado.
- **Reprocessamento:** a resposta crua fica em `data/raw/ipca-inpc/` (gzip, 46 MB para os 880 arquivos), então refazer a transformação não exige chamar a API de novo.
- **Escrita transacional:** nenhuma nesta fonte. A carga é em lote, por mês, e no desenho atual reexecutar o mesmo mês não duplica linhas.

### Taxa de leitura e padrão de acesso

Leitura da **origem** (a API):

| # | Consulta | Frequência | Tipo | Acesso |
|---|---|---|---|---|
| 1 | Metadados do agregado (categorias e hierarquia) | 1 por agregado por rodada (3 no regime) | pontual | `servicodados.ibge.gov.br/api/v3/agregados/{id}/metadados` |
| 2 | Valores de um mês | 1 por agregado ativo por mês (3 no regime) | lote | `apisidra.ibge.gov.br/values/t/{agregado}/.../p/{AAAAMM}/f/c/h/n` |
| 3 | Calendário de divulgação | 1 por mês (recomendado; hoje não implementado) | pontual | `servicodados.ibge.gov.br/api/v3/calendario` |

Leitura do **armazenamento** (as perguntas do lojista). A leitura domina (estimativa de 95%+ das operações):

| # | Consulta | Frequência | Tipo | Latência alvo | Acesso |
|---|---|---|---|---|---|
| 1 | Inflação acumulada do meu setor em 12 meses | ~5/lojista/dia | pontual | < 300 ms | filtro por (subitem, localidade, variável 2265), 1 linha |
| 2 | Meses do ano com maior pico histórico | ~1/lojista/dia | agregada | < 5 s | `GROUP BY` mês do ano sobre ~240 meses (2938 + 1419 + 7060 unificadas) |
| 3 | Impacto no poder de compra desde 2006 | < 1/lojista/dia | agregada | < 5 s | razão de dois números-índice do 1737 (exato, só índice geral Brasil) ou produto de 241 variações mensais |
| 4 | Inflação geral × da minha região em 5 anos | ~1/lojista/dia | agregada | < 300 ms | autojunção da `observacao`: Brasil × praça do lojista |
| 5 | Reajuste mínimo para não perder margem | ~10/lojista/dia | pontual + escrita | < 300 ms | junta `produto` com `observacao` pela FK do subitem |

O índice `observacao_consulta_idx (codigo_classificacao, codigo_localidade, codigo_variavel, mes_referencia desc)` cobre 1, 4 e 5 diretamente. Frequências são estimativas de uso: ainda não há usuário.


---

## 4. Restrições que a origem impõe

- **Teto de 50.000 valores por requisição.** Um mês do 7060 são 31.076 valores e passa; dois meses (62.152) devolvem HTTP 400. Paginar por mês é imposição, não escolha.
- **~30% das linhas são marcadores de ausência** (medido no 7060). Só `-` e `...` aparecem nos dados carregados; a ajuda da API também define `..` e `X`. O `-` é a ausência de categoria não pesquisada numa localidade, mas a ajuda o define como "zero absoluto". O código o trata como ausente, o que é coerente com o padrão observado, mas **não está confirmado** na documentação. `-0.67` é deflação real, e filtrar por prefixo `-` apagaria esses meses sem erro.
- **Mês ainda não divulgado devolve lista vazia (`[]`)**, sem erro. Uma janela `--ate` além do último mês publicado apenas não traz linhas, e não há sinal de que "faltou dado". Convém checar o calendário antes de rodar.
- **Esquema heterogêneo.** O agregado 2938 não publica o acumulado em 12 meses e cobre 12 localidades em vez de 17. Ingerir com o mesmo código, sem tratar o caso, produz série truncada sem erro.
- **A cesta muda de estrutura.** 43 subitens renomeados com código estável, 111 removidos e 103 acrescentados entre 2006 e 2026. Os valores identificam a categoria pelo `id` interno do SIDRA (`D4C`), não pelo código natural; a tradução vem do endpoint de metadados.
- **Sem carga incremental por filtro.** A origem é consultada por período, então "novo" é definido por mês. Não há como pedir "só o que mudou": uma revisão de mês já carregado só é vista se o mês for baixado de novo.
- **Separador decimal é ponto** (`-0.67`), diferente do `.xlsx` da interface web, que usa vírgula.
