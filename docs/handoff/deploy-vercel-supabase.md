# Handoff: colocar o site do InflaTrack no ar (Vercel + Supabase)

Guia para o agente que vai preparar o deploy. Escrito em 2026-11-24, na branch `feat/site`.
Leia este arquivo inteiro antes de mexer em código, e confirme cada fato no código, porque ele
pode ter mudado depois desta data.

## Objetivo

Publicar o site (frontend Next.js + backend FastAPI) usando a Vercel e o Supabase, de modo que
uma pessoa consiga criar conta, entrar, ver o dashboard de qualquer praça e conversar com a
Felicia.

Não faz parte desta tarefa: o pipeline de dados (Dagster/dbt). Ele continua rodando na máquina
local e publica os resultados no Supabase. Ver `docs/como_rodar/publicar_site.md`.

## Regras do projeto que valem para você

- **A cada 3 mensagens do usuário, atualize o `AI-USAGE.md`** (regra do `CLAUDE.md`). Siga o
  formato das entradas que já existem: "O que a ferramenta fez", "O que foi verificado e como" e
  "O que NÃO foi verificado".
- **Não adicione `Co-Authored-By: Claude`** nos commits.
- Perguntas de decisão devem dizer de onde veio cada fato (autor ou commit) e explicar o jargão.
- **Sem permissão de administrador.** Não rode `sudo` nem instaladores globais. Peça ao usuário.
- **Não faça deploy, não crie projeto na Vercel e não altere o Supabase de produção sem
  confirmação do usuário.** São ações externas e difíceis de desfazer. Mostre o comando ou o
  passo e espere o "ok".
- Nunca coloque segredos (`.env`, chaves, senhas) em commit, log ou no `AI-USAGE.md`.
- O usuário escreve em português. Responda em português.

## Estado atual (2026-11-24)

- Branch `feat/site`, à frente da `main`. O último commit é `6f93704`. Ainda não estão
  commitados o ajuste visual do dashboard (`web/frontend/app/globals.css`), a correção do filtro
  "Brasil" (`web/frontend/app/page.tsx`), a skill `.claude/skills/ui-ux-pro-max/` e o
  `AI-USAGE.md`. Pergunte ao usuário se ele quer commitar isso antes de começar.
- Rodando localmente: o frontend em `localhost:3000` e o backend em `localhost:8000`.
- **Conta de teste:** peça ao usuário. Não escreva a senha em nenhum arquivo.

## Arquitetura

```
navegador ──> web/frontend (Next.js 16.4, React 19)   ──fetch, credentials: "include"──>
              web/backend  (FastAPI, Python)           ──> Supabase (Auth + Postgres)
                                                       ──> proxy LiteLLM (Felicia, via Google ADK)
```

### Frontend: `web/frontend/`

- `npm run build` e `npm start`. A Vercel detecta Next.js sozinha; o **Root Directory** do
  projeto deve ser `web/frontend`.
- Única variável: `NEXT_PUBLIC_API_URL`. O padrão é `http://localhost:8000` e está definido em
  `app/dashboard/formato.tsx`. Ela também aparece em `app/login/page.tsx` e, possivelmente, em
  outras telas (confira com grep).
- `proxy.ts` (o "middleware" do Next 16) redireciona `/` para `/login` quando não encontra os
  cookies `inflatrack_access_token` ou `inflatrack_refresh_token`.
- `next.config.ts` usa opções experimentais (`agentFeedback`, `cacheComponents`,
  `partialPrefetching`). Confira se o build passa na Vercel com elas.
- Leia `web/frontend/AGENTS.md` antes de mexer no frontend.

### Backend: `web/backend/`

- FastAPI em `app.py`. Também tem `chat.py` (Felicia), `publicacao.py` (leitura das tabelas
  publicadas), `database.py` (SQLAlchemy + psycopg), `migrations/001..004_*.sql` e `tests/`.
- Dependências em `requirements.txt`: fastapi, uvicorn, SQLAlchemy, psycopg[binary], httpx,
  google-adk e litellm. **google-adk e litellm são pacotes grandes**, e isso pesa na escolha de
  onde o backend vai rodar (ver a decisão 1).
- Variáveis (`web/backend/.env.example`): `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`,
  `CORS_ORIGINS`, `COOKIE_SECURE`, `DATABASE_URL` (pooler, porta 6543), `DIRECT_URL` (porta 5432,
  só para aplicar o esquema), `LITELLM_PROXY_URL`, `LITELLM_API_KEY` e `LITELLM_MODEL`.
- O login usa o Supabase Auth, e o backend grava os tokens em cookies httpOnly com
  `samesite="lax"` e `secure=COOKIE_SECURE` (`app.py`, por volta das linhas 186–215 e 390).
- Commits anteriores tiraram os prepared statements por causa do pooler do Supabase (commit
  `49d2d11`). Não volte com eles.

### Supabase

- Esquema: aplique `web/backend/migrations/` em ordem, usando a `DIRECT_URL`.
- Dados: as 6 tabelas publicadas pelo pipeline local estão descritas em
  `docs/como_rodar/publicar_site.md`. Verifique se a produção já tem os dados, ou se é preciso
  publicar antes.
- Auth: configure a **Site URL** e as **Redirect URLs** com o domínio final da Vercel (confirmação
  de e-mail e recuperação de senha).

## Problema que vai bloquear o deploy: cookies entre domínios

Localmente tudo roda em `localhost`, e o cookie gravado pela porta 8000 aparece também na porta
3000. Em produção:

1. Se o backend ficar em outro domínio (por exemplo `api-x.vercel.app` ou `x.onrender.com`), o
   cookie fica nesse domínio. O `proxy.ts` do frontend **nunca o vê**, e o usuário volta para
   `/login` para sempre.
2. Com `samesite="lax"`, o navegador não envia o cookie em `fetch` entre sites diferentes. Então
   até as chamadas de API falhariam com 401.

**Solução recomendada:** servir a API pelo mesmo domínio do site. No `next.config.ts`, adicione um
`rewrites()` que mande `/api/:path*` para a URL do backend, e use `NEXT_PUBLIC_API_URL=/api` (ou
caminhos relativos). Assim os cookies ficam no domínio do site, o `proxy.ts` volta a funcionar e o
CORS deixa de ser necessário em produção.

Atenção: o código monta as URLs com `.replace(/\/$/, "")` e `${apiUrl}/...`. Confira se uma URL
relativa funciona em todos os pontos, inclusive no streaming da Felicia, se houver.

A alternativa (`samesite="none"` + `secure` + domínio próprio com subdomínios) é mais frágil.
Só use se o usuário pedir.

## Decisões para levar ao usuário

Pergunte com contexto, conforme as regras acima, e não decida sozinho:

1. **Onde roda o backend FastAPI.**
   - (a) Na Vercel, como função Python, em outro projeto ou no mesmo repositório. É grátis e fica
     num lugar só, mas tem limite de tamanho do pacote e de tempo por requisição. O google-adk e o
     litellm podem passar do limite, e o chat da Felicia pode passar do tempo. Meça antes.
   - (b) Num serviço de contêiner ou de processo contínuo (Render, Railway, Fly.io), com o
     frontend fazendo o rewrite para ele. É mais previsível para o chat, mas é mais uma conta.
2. **O domínio** (`*.vercel.app` ou um domínio próprio).
3. **Qual projeto Supabase é a produção**, e se é o mesmo usado nos testes.
4. **Quem guarda os segredos** (`LITELLM_API_KEY` etc.). Eles vão para as variáveis de ambiente da
   Vercel ou do provedor, nunca para o repositório.

## Plano sugerido

1. Leia este guia, `docs/como_rodar/publicar_site.md`, `web/backend/README.md`,
   `web/frontend/README.md` e `web/frontend/AGENTS.md`.
2. Rode os testes locais: no backend, `pytest web/backend/tests`; no frontend,
   `npx tsc --noEmit`, `npm run lint` e **`npm run build`** (o build de produção ainda não foi
   testado).
3. Leve as decisões 1–4 ao usuário.
4. Implemente o rewrite `/api` e ajuste `NEXT_PUBLIC_API_URL`. Teste localmente com
   `npm run build && npm start`, apontando para o backend local.
5. Prepare a configuração do backend escolhido (por exemplo `vercel.json` ou `api/index.py` para a
   Vercel, ou `Dockerfile`/`render.yaml`) e um `.env.example` com todas as variáveis de produção.
   Em produção, `COOKIE_SECURE=true`.
6. Escreva `docs/como_rodar/deploy_vercel.md` com o passo a passo, para o grupo repetir o deploy.
7. Com confirmação do usuário: crie os projetos, configure as variáveis, faça o deploy e ajuste as
   URLs no Supabase Auth.
8. Valide em produção: cadastro, login, dashboard de Brasil e de uma praça, troca de abas, uma
   pergunta à Felicia e logout. Teste em largura de celular também.

## Como ver a tela (validação visual)

Na sessão anterior, um script Node abria o Microsoft Edge sem janela (já instalado em
`C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`) via Chrome DevTools Protocol:

- fazia login com `fetch` em `POST /auth/login` de dentro da página;
- abria `/`;
- tirava prints em 1920, 1366 e 390 px.

A senha ia por variável de ambiente, nunca por arquivo. O script ficava na pasta temporária da
sessão, então recrie um parecido se precisar. Em produção, troque `localhost` pelas URLs reais.

## Pronto quando

- `npm run build` passa, e os testes do backend passam.
- Login, dashboard e Felicia funcionam na URL pública, com cookies `Secure`.
- Nenhum segredo está no repositório.
- `docs/como_rodar/deploy_vercel.md` existe, e o `AI-USAGE.md` foi atualizado.
