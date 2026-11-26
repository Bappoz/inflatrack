# Como publicar no site (Supabase)

O que fazer para colocar a previsão, os gráficos e o dashboard no Supabase do site. O site e a
Felicia leem **só** o Supabase: o modelo é treinado e tudo é calculado na máquina local, e só o
resultado sobe. A primeira vez exige os
passos 1 a 3. Depois, só o passo 4, ou o agendamento do passo 6.

## O que vai para o Supabase

São só 6 tabelas pequenas, com cerca de 1 MB de dados (medido em 2026-11-24). Nenhuma tem preço
nem dado de usuário:

| Tabela | O que é | Linhas |
|---|---|---|
| `previsao_subitem` | Variação prevista para o mês seguinte, por praça e subitem, com o erro típico | ~4.000 |
| `subitem` | Nome e grupo de cada subitem, para buscar o produto | ~380 |
| `uf_praca` | A praça do IPCA de cada UF (UF sem praça usa o Brasil) | 27 |
| `resumo_subitem` | IPCA do último mês, por praça e subitem (mês e 12 meses) | ~4.000 |
| `painel_grafico` | Os 6 gráficos do painel do lojista, já calculados | 6 |
| `dashboard_localidade` | O dashboard de inflação de cada praça (KPIs, setores, praças, histórico inteiro, sazonalidade, poder de compra). O backend só recorta o período | 17 |

Quem lê o quê:

- `GET /dashboard`: `dashboard_localidade`.
- Felicia: `consultar_inflacao` lê o dashboard do Brasil; `buscar_produto` lê `subitem`;
  `prever_reajuste` lê `uf_praca`, `previsao_subitem` e `resumo_subitem` e devolve
  preço x (1 + variação prevista), com a faixa de +/- erro. O preço que o lojista digita não é
  gravado.

Cada publicação **apaga e reescreve** as 6 tabelas numa transação só. Ou entra tudo, ou o site
continua com a publicação anterior. Nada antigo fica acumulado.

## Antes de começar

- Ambiente local no ar, com a Gold atualizada: `just up` e o `analitico_job` já rodado pelo
  menos uma vez.
- Acesso de dono ao projeto do Supabase do site.

## 1. Criar as tabelas no Supabase (uma vez)

1. No painel do Supabase, abra o projeto do site e vá em **SQL Editor > New query**.
2. Cole o conteúdo inteiro de `web/backend/migrations/003_publicacao_inflatrack.sql` e clique em
   **Run**. Repita com `web/backend/migrations/004_dashboard_localidade.sql`.
3. Confira em **Table Editor** se as 6 tabelas apareceram, todas com o selo **RLS enabled**.

O arquivo pode ser rodado de novo sem problema: ele só cria o que falta e refaz as permissões.
As permissões deixam qualquer visitante do site ler as 6 tabelas, mas ninguém escrever. Só a
conexão do passo 2 escreve.

## 2. Copiar a URL de conexão

1. No Supabase, clique em **Connect**, no topo do projeto, ou vá em **Project Settings >
   Database**.
2. Escolha a aba **Connection string > URI** e o modo **Session pooler**.
   - **Use o Session pooler, não a "Direct connection"**: no plano gratuito, a conexão direta só
     funciona por IPv6, e a maioria das redes domésticas não tem.
   - O "Transaction pooler" (porta `6543`) também funciona, porque a publicação não usa comandos
     preparados. O Session pooler é o mais simples.
3. A URL tem este formato:

   ```
   postgresql://postgres.<id-do-projeto>:<SENHA>@aws-0-<regiao>.pooler.supabase.com:5432/postgres
   ```

4. Troque `<SENHA>` pela senha do banco, definida na criação do projeto. Se não lembrar, gere
   outra em **Project Settings > Database > Reset database password**.
   - Se a senha tiver caracteres como `@`, `#`, `/` ou `%`, eles precisam ser codificados na URL
     (`@` vira `%40`, `#` vira `%23`). O mais simples é gerar uma senha sem esses caracteres.

> Essa URL dá acesso total ao banco do site. Ela fica **só no seu `.env`**, que não vai para o
> Git. Nunca a coloque no código, no `.env.example`, num print ou numa mensagem. O site usa outra
> chave, a pública (`anon`), que só lê.

## 3. Preencher o `.env` (uma vez)

No `.env` da raiz do projeto, preencha a linha que já existe:

```bash
SUPABASE_DB_URL=postgresql://postgres.<id-do-projeto>:<senha>@aws-0-<regiao>.pooler.supabase.com:5432/postgres
```

Se o seu `.env` for anterior a esta mudança e não tiver a linha, copie-a do `.env.example`.

## 4. Gerar a previsão e publicar

```bash
just previsao        # prevê o mês seguinte para cada praça e subitem (~5 min)
just publicar-site   # grava as 6 tabelas no Supabase (alguns segundos)
```

Se tudo der certo, o `just publicar-site` termina com algo assim:

```
INFO previsao_subitem: 4045 linhas
INFO subitem: 377 linhas
INFO uf_praca: 27 linhas
INFO resumo_subitem: 4045 linhas
INFO painel_grafico: 6 linhas
INFO dashboard_localidade: 17 linhas
```

Pelo Dagster dá no mesmo. Dois jobs terminam no `site_supabase`:

- **`predicao_job`**: gera a previsão nova (`fct_previsao_subitem`) e publica.
- **`dashboard_job`**: carrega o IPCA, roda o dbt, copia para a `serie` e publica. É o que
  atualiza o dashboard do site quando sai um IPCA novo. Ele republica a última previsão local,
  então precisa que o `predicao_job` (ou `just previsao`) já tenha rodado uma vez.

## 5. Conferir no Supabase

No SQL Editor:

```sql
-- Mês previsto e quantas previsões entraram
select mes_previsto, count(*) from previsao_subitem group by 1;

-- Arroz em Brasília: o site mostraria preço x (1 + variação), com faixa de +/- erro
select s.nome, p.variacao_prevista_pct, p.erro_tipico_pct
from previsao_subitem p join subitem s using (codigo_subitem)
where p.codigo_localidade = 5300108 and p.codigo_subitem = '1101002';
```

## 6. Deixar automático (opcional)

O `predicao_job` tem agendamento para todo **dia 14, às 11h**, depois da janela de divulgação do
IPCA (dias 9 a 13). Como todos os agendamentos do projeto, ele nasce **desligado**. Para ligar:
**Automation > predicao_job** na interface do Dagster. O computador com o Dagster precisa estar
ligado nesse horário.

## Se der errado

| Mensagem | Causa e solução |
|---|---|
| `SUPABASE_DB_URL vazio` | O passo 3 não foi feito, ou a linha está em branco. |
| `connection timed out` / `Network is unreachable` | Foi usada a "Direct connection" (só IPv6). Troque pela URL do **Session pooler** (passo 2). |
| `password authentication failed` | A senha está errada ou tem caractere especial sem codificar (passo 2, item 4). |
| `publicação recusada, tabelas vazias: ...` | A Gold ou a `serie` local estão sem dado (por exemplo, num clone novo). Rode o `analitico_job` e `just previsao`. Nada foi apagado no Supabase. |
| `o gráfico ... tem coluna de preço` | Alguém pôs no painel uma pergunta com preço ou custo. Preço não vai para o Supabase (ADR 0004): tire a coluna ou a pergunta. |
| `relation "previsao_subitem" does not exist` | O passo 1 não foi feito no Supabase. |
| `Table with name fct_previsao_subitem does not exist` | Falta gerar a previsão local: `just previsao`. |
| `Could not set lock on file ... inflatrack.duckdb` | Outro processo está escrevendo no DuckDB (dbt ou uma carga). Espere ele terminar e rode de novo. |

Uma publicação que falha no meio não apaga nada: o site continua com a última publicação que deu
certo.
