# Colocar o site no ar (Vercel + Supabase)

Este guia publica o site do InflaTrack: o frontend Next.js e o backend FastAPI, cada um num
projeto da Vercel, os dois usando o Supabase que já tem os usuários e os dados do dashboard.

O pipeline de dados (Dagster/dbt) **não** vai para a Vercel. Ele continua rodando na máquina de
alguém do grupo e publica as tabelas no Supabase (ver [publicar_site.md](publicar_site.md)).

## Como as peças se ligam

```
navegador ──> site (Vercel, web/frontend) ──/api/*──> API (Vercel, web/backend) ──> Supabase
                                                                                ──> proxy LiteLLM
```

O navegador só fala com o domínio do site. Tudo o que começa com `/api/` é repassado pelo Next
para a API (é o `rewrites()` em `web/frontend/next.config.ts`). Assim os cookies de login ficam no
domínio do site, onde o `proxy.ts` consegue vê-los. Se o navegador chamasse a API direto, em
outro domínio, o login entraria num laço de volta para `/login`.

## Antes de começar

- Uma conta na Vercel (o plano Hobby, gratuito, basta) com acesso ao repositório no GitHub.
- Acesso ao painel do Supabase do projeto.
- Os valores do `web/backend/.env` de quem já roda o site localmente. Você vai **copiar e colar**
  esses valores no painel da Vercel. Eles nunca vão para o repositório.
- A Vercel publica em produção a branch `main`. Se o código do site ainda estiver em outra
  branch, faça o merge antes, ou troque a **Production Branch** em *Settings → Environments*.

## 1. Projeto da API (backend)

1. Na Vercel, clique em **Add New → Project** e importe o repositório.
2. Em **Root Directory**, escolha `web/backend`. A Vercel reconhece o FastAPI sozinha pelo
   `app.py` e instala o `requirements.txt` com Python 3.12 (`.python-version`).
3. Dê um nome curto ao projeto, como `inflatrack-api`. Esse nome vira a URL
   `https://inflatrack-api.vercel.app`.
4. Em **Environment Variables**, cadastre:

   | Variável | Valor |
   |---|---|
   | `SUPABASE_URL` | igual ao `.env` local |
   | `SUPABASE_PUBLISHABLE_KEY` | igual ao `.env` local |
   | `DATABASE_URL` | igual ao `.env` local (o *pooler*, porta **6543**) |
   | `LITELLM_PROXY_URL` | igual ao `.env` local |
   | `LITELLM_API_KEY` | igual ao `.env` local |
   | `LITELLM_MODEL` | `gpt-5.4-mini` (**sem** o prefixo `openai/`, que dá erro 403) |
   | `COOKIE_SECURE` | `true` |
   | `CORS_ORIGINS` | a URL do site (passo 2), ex.: `https://inflatrack.vercel.app` |

   A `DIRECT_URL` não é necessária: ela só serve para aplicar o esquema com `python database.py`.
5. Clique em **Deploy**. Quando terminar, abra `https://<api>.vercel.app/health`. Deve aparecer
   `{"status":"ok"}`.

## 2. Projeto do site (frontend)

1. **Add New → Project** de novo, com o mesmo repositório.
2. Em **Root Directory**, escolha `web/frontend`. O preset é **Next.js**.
3. Dê o nome do site, como `inflatrack`, para ter a URL `https://inflatrack.vercel.app`.
4. Em **Environment Variables**, cadastre só uma variável:

   | Variável | Valor |
   |---|---|
   | `BACKEND_URL` | a URL da API do passo 1, ex.: `https://inflatrack-api.vercel.app` |

   **Não** cadastre `NEXT_PUBLIC_API_URL`. Sem ela, o site usa `/api` no próprio domínio, que é o
   que faz o login funcionar.
5. Clique em **Deploy**. A `BACKEND_URL` é lida durante o build. Se você mudar o valor depois,
   faça um **Redeploy**.

Se o nome que você queria para o site já estava em uso, a URL será outra. Nesse caso, corrija o
`CORS_ORIGINS` da API e faça um **Redeploy** dela.

## 3. Supabase Auth

No painel do Supabase, abra **Authentication → URL Configuration**:

- **Site URL**: a URL do site, ex.: `https://inflatrack.vercel.app`. É para onde vão os links de
  confirmação de e-mail.
- **Redirect URLs**: acrescente `https://inflatrack.vercel.app/**`. Mantenha
  `http://localhost:3000/**` se o grupo ainda testa localmente.

O esquema do banco e as 6 tabelas do dashboard já estão no Supabase (conferido em 2026-11-26).
Para um projeto Supabase novo, siga a seção 1 de [publicar_site.md](publicar_site.md) e rode
`python database.py` em `web/backend`.

## 4. Conferir em produção

Na URL do site, num navegador comum e na largura de celular:

1. Criar uma conta em `/cadastro` e confirmar o e-mail. O link deve abrir o site, não o
   `localhost`.
2. Entrar em `/login` e ver o dashboard de **Brasil**. Depois, trocar para uma praça e trocar as
   abas.
3. Fazer duas perguntas seguidas à Felicia, com a segunda dependendo da primeira (ex.: "Qual o
   IPCA em 12 meses?" e depois "E o INPC?"). Se a segunda for entendida, o histórico chegou.
4. Sair (logout) e conferir que `/` volta para `/login`.

A primeira pergunta à Felicia depois de um tempo parado pode demorar uns 15 s. É o proxy do
modelo "acordando" (*partida a frio*). A API tenta mais uma vez sozinha quando isso acontece.

## Quando algo dá errado

| Sintoma | Causa provável e solução |
|---|---|
| Depois do login, volta para `/login` | `NEXT_PUBLIC_API_URL` cadastrada no site com a URL da API. Apague e faça o redeploy. |
| Login e dashboard dão erro 500 ou "Não consegui falar com o servidor" | `BACKEND_URL` ausente ou errada no site, ou o site não foi refeito depois de mudá-la. |
| "A Felicia não está configurada." | Faltam `LITELLM_PROXY_URL` ou `LITELLM_API_KEY` na API. |
| "A Felicia não conseguiu responder agora." sempre | `LITELLM_MODEL` com o prefixo `openai/`, chave errada ou proxy fora do ar. Veja os logs em *API → Logs*. |
| "Dados indisponíveis..." no dashboard | `DATABASE_URL` errada ou sem a porta 6543 do pooler. |
| Link de confirmação abre o `localhost` | **Site URL** do Supabase Auth ainda está com o endereço local (passo 3). |

## Atualizar o site

Cada `git push` na branch de produção refaz os dois projetos sozinho. Os dados do dashboard não
dependem de deploy: basta publicar de novo pelo pipeline ([publicar_site.md](publicar_site.md)).
