# Aplicação do modelo e publicação no Supabase — design

Data: 2026-11-19 · Branch `feat/aplicacao-modelo`, empilhada sobre `feat/modelo-reajuste` (#24)

Primeiro de três trabalhos da fase de aplicação: (1) **este**, que é prever e publicar; (2) o
site novo; (3) o agente Google ADK. O site e o agente leem só o que este trabalho publica.

## Por que

O site deve dizer ao pequeno lojista, sem tabela para interpretar, algo como "suba o preço do
arroz para R$ 25,55". O site não tem acesso ao ambiente local (o Docker com Postgres e DuckDB). Por
isso, o modelo é treinado e aplicado **localmente**, e só os valores já calculados vão para o
**Supabase** (plano gratuito; o mínimo possível). O usuário digita o preço que paga, e o site faz
a conta `preço × (1 + variação prevista)`. O preço digitado não é gravado.

## Decisões do integrante

- Previsão para **todos os subitens de todas as praças**, e não só os 45 do atacadista: o usuário
  pode perguntar por qualquer produto.
- ~~Um modelo por subitem~~: substituído pelo **XGBoost fixo** depois do ponto de parada (abaixo).
- Antes de adotar, **refazer a avaliação com todos os subitens e todas as praças**.
- Treino e aplicação locais; o Supabase guarda só o resultado.
- Caminho **misto**:
  - os gráficos do **painel do lojista do Metabase** (não os de clima) vão como resultado pronto;
  - o agente recebe a previsão e um resumo do último mês.
- **Retenção:** cada publicação apaga e reescreve as tabelas. Nada fica fora da janela.

## Objetivos

1. Avaliação ampliada: o walk-forward de 36 meses com todos os subitens do IPCA em todas as
   praças.
2. `gold.fct_previsao_subitem`: a variação prevista para o mês seguinte ao último IPCA, por praça
   e subitem, com o erro típico do XGBoost.
3. Publicação no Supabase de seis tabelas pequenas, com leitura pública e escrita só a partir do
   ambiente local.
4. Orquestração no Dagster, uma vez por mês, depois do IPCA.

## Não objetivos

- O site e o agente (trabalhos 2 e 3).
- Gravar preço no Supabase, ou qualquer dado do usuário.
- Publicar os gráficos de clima.
- A `public.recomendacao_reajuste` do plano original: ela deixa de ser necessária, porque a conta
  em R$ acontece no site com o preço digitado.

## Anti-objetivos

- Vazar o futuro: a escolha do modelo por subitem e o erro típico vêm só de meses já divulgados.
- O site ou o agente acessarem o ambiente local.
- Credencial no repositório: a URL do Supabase fica só no `.env`, e o `.env.example` leva o campo
  vazio.

## Abordagens consideradas

1. **Escolhida, pelo integrante e com o ajuste da ferramenta:** treinar e aplicar localmente e
   publicar o mínimo no Supabase. O site faz só `preço × (1 + variação)`.
2. Tudo no Postgres local, com o site lendo dele. Descartada: o site não tem acesso ao ambiente
   local.
3. Publicar recortes inteiros da `serie` (por exemplo, 24 meses de `fct_inflacao_mensal`).
   Descartada: centenas de milhares de linhas, e a conta iria para o site.

## Parte 1 — Avaliação ampliada (ponto de parada)

**Decisão do integrante: a Parte 1 é um ponto de parada.** Ela é construída e executada sozinha.
Os números vão para o integrante, e as Partes 2 a 4 só começam depois que ele os revisar e
liberar. Se o resultado pedir outro modelo, outra janela de escolha ou outra regra de reserva,
este design é atualizado antes.

- `montar_base` passa a aceitar várias praças: a chave vira `(codigo_localidade,
  codigo_subitem)`, e `codigo_localidade` entra como variável categórica.
- Base: todos os subitens do IPCA, com cerca de 881 mil linhas e 478 subitens.
- Modelos: ingênua, ingênua sazonal, regressões linear e logarítmica pela tendência e **XGBoost sem
  clima**. O clima saiu pela avaliação anterior. As regressões pelo nível também saem, porque já
  ficou mostrado que perdem.
- O XGBoost é **um modelo único** treinado com todas as praças e subitens. *Decisão da
  ferramenta:* dá mais dados por subitem raro do que um modelo por praça.
- Novo notebook `notebooks/avaliacao_todas_pracas.ipynb`, com a evidência atualizada em
  `docs/evidencias/e4/`:
  - MAE geral, por praça e por grupo;
  - o modelo vencedor por subitem.
  
  Pode levar dezenas de minutos, mas roda uma vez só.

## Resultado do ponto de parada (2026-11-19)

A avaliação ampliada (`docs/evidencias/e4/avaliacao_todas_pracas.md`) mostrou:
- o XGBoost único ganha da ingênua em todas as 17 localidades (+29% no geral);
- a escolha por subitem melhora só cerca de 1% sobre ele, nos meses que ela não viu.

**Decisão do integrante: XGBoost fixo.** A escolha por subitem e a regra de reserva saem do
design.

## Parte 2 — Previsão na Gold

- Modelo Python do dbt `gold.fct_previsao_subitem`, com uma linha por `(codigo_localidade,
  codigo_subitem)`:
  - `mes_base`: último IPCA divulgado;
  - `mes_previsto`: `mes_base` + 1;
  - `variacao_prevista_pct`;
  - `erro_tipico_pct`;
  - `gerado_em`.
- **Previsão:** o XGBoost sem clima (variáveis `FEATURES_BASE`, praça como categoria), treinado
  com todas as linhas de mês <= `mes_base` − 1 que têm alvo, prevê a linha de `mes_base` de cada
  série. Uma série sem IPCA em `mes_base` não recebe previsão.
- **Erro típico:** o MAE do XGBoost por subitem, juntando as praças, num walk-forward dos
  **últimos 12 meses** (12 treinos). Sem nenhuma previsão nessa janela, usa-se o MAE do grupo do
  IPCA (primeiro dígito).
- Fica fora do `analitico_job` diário (são 13 treinos, alguns minutos). Entra no grupo `predicao`.
- Testes do dbt: chave única; `variacao_prevista_pct` e `erro_tipico_pct` não nulos;
  `erro_tipico_pct >= 0`.
- *Decisão da ferramenta:* **não há cópia para a `serie`.** Quem lê a previsão é o site e o
  agente, pelo Supabase, e não o Metabase. A publicação lê a Gold direto, só para leitura e
  dentro do pool `duckdb_writer`. Com isso, a migration `0008` sai do design.

## Parte 3 — Publicação no Supabase

Módulo `inflatrack.reverse_etl.publicar_site`. Ele lê a previsão na Gold (DuckDB, só leitura) e
os gráficos e o resumo no Postgres **local** (`serie`), e grava no
Supabase pela URL de Postgres do projeto, na variável `SUPABASE_DB_URL`. Tudo acontece numa
transação: apaga e insere cada tabela, então ou a publicação inteira entra, ou nada muda.

| Tabela no Supabase | Conteúdo | Linhas |
|---|---|---|
| `previsao_subitem` | a `gold.fct_previsao_subitem` inteira | ~4.000 |
| `subitem` | código, nome (versão atual da cesta), código e nome do grupo | ~478 |
| `uf_praca` | UF → `codigo_localidade` e nome da praça (UF sem praça → Brasil, `1`) | 27 |
| `resumo_subitem` | último mês, por praça e subitem: variação do mês e de 12 meses | ~4.000 |
| `painel_grafico` | `id`, `titulo`, `linhas` (jsonb com o resultado do SQL), `ate_o_mes` | 6 |

- **`painel_grafico`** recebe o resultado dos SQLs do painel do lojista, já existentes em
  `scripts/sql/metabase/`: `p1_inflacao_12m_por_setor`, `p2_sazonalidade_por_mes`,
  `p3_poder_de_compra_desde_2006`, `p3_salario_minimo_real`, `p4_brasil_ipca_x_inpc_5_anos` e
  `p4_brasil_x_regiao`. O `p5_reajuste_minimo_por_produto` não entra, porque o formulário do chat
  o substitui. *Decisão da ferramenta:* uma tabela genérica com `jsonb` em vez de uma por gráfico.
  É o mínimo de estrutura, e um gráfico novo não pede migration.
- **UF → praça**: Belém (PA), Fortaleza (CE), Recife (PE), Salvador (BA), Belo Horizonte (MG),
  Grande Vitória (ES), Rio de Janeiro (RJ), São Paulo (SP), Curitiba (PR), Porto Alegre (RS), Rio
  Branco (AC), São Luís (MA), Aracaju (SE), Campo Grande (MS), Goiânia (GO) e Brasília (DF). As
  outras 11 UFs ficam com o Brasil.
- **Esquema no Supabase:** `web/backend/migrations/003_publicacao_inflatrack.sql`, no mesmo lugar
  das migrations do site. Tudo fica em `public`, com RLS ligado e uma política de `select` para
  `anon` e `authenticated`. Não há política de escrita: só a conexão do dono, usada pelo ambiente
  local, escreve. O integrante aplica o arquivo no painel do Supabase.
- **`.env.example`**: o campo `SUPABASE_DB_URL=` vai vazio, e o integrante preenche.

## Parte 4 — Orquestração

- `predicao_job` (mensal, dia 14 às 11h, depois da janela do IPCA nos dias 9 a 13) roda:
  1. `fct_previsao_subitem` (dbt);
  2. `site_supabase`.
- `site_supabase` não tem dependentes. Sem `SUPABASE_DB_URL`, ele falha com uma mensagem clara e
  sem retry.
- `just publicar-site` faz o mesmo pelo terminal.

## Testes

- `montar_base` com duas praças: as defasagens não atravessam praças, e a chave inclui a praça.
- Previsão: o mês previsto é `mes_base + 1`; uma série sem dado em `mes_base` fica fora; o
  treino só usa linhas de mês <= `mes_base` − 1.
- Erro típico: vem só da janela de 12 meses até `mes_base`; um subitem sem previsão na janela
  recebe o MAE do grupo.
- Publicação contra um Postgres descartável, que faz o papel do Supabase:
  - cria as tabelas pela migration `003`;
  - publica duas vezes, e o número de linhas não dobra (retenção);
  - um erro no meio da publicação não deixa tabela vazia (transação);
  - `anon` lê e não escreve.
- Os 6 SQLs do painel rodam contra a `serie` local e viram `jsonb`.

## Fica para quem implementar

- Como o grupo `predicao` é atribuído no `dbt_assets.py`, e como tirar o modelo do `analitico_job`.
- O formato exato do `jsonb` de cada gráfico (lista de objetos coluna → valor).
