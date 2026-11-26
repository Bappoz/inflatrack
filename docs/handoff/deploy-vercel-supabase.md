# Handoff: colocar o site do InflaTrack no ar (Vercel + Supabase)

Guia para o agente que vai preparar o deploy. Escrito em 2026-11-24 e revisado em 2026-11-26, na
branch `feat/site`. Leia este arquivo inteiro antes de mexer em código, e confirme cada fato no
código, porque ele pode ter mudado depois dessas datas.

## Objetivo

Publicar o site (frontend Next.js + backend FastAPI) usando a Vercel e o Supabase, de modo que
uma pessoa consiga criar conta, entrar, ver o dashboard de qualquer praça e conversar com a
Felicia.

Não faz parte desta tarefa: o pipeline de dados (Dagster/dbt). Ele continua rodando na máquina
local e publica os resultados no Supabase. Ver `docs/como_rodar/publicar_site.md`.

## Decisões já tomadas pelo usuário

Não pergunte de novo. Execute.

1. **O Google ADK sai do backend.** A Felicia passa a chamar o proxy LiteLLM direto, com `httpx`.
   Detalhes e motivos na seção "Felicia" abaixo.
2. **O histórico da conversa com a Felicia fica no navegador.** A cada pergunta, o frontend envia as
   **10 últimas mensagens anteriores** como contexto. O servidor não guarda estado.

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

## Estado atual (2026-11-26)

- Branch `feat/site`, à frente da `main`. O último commit é `115c8e2`, e nele já estão o ajuste
  visual do dashboard, a correção do filtro "Brasil", a skill `.claude/skills/ui-ux-pro-max/` e o
  `AI-USAGE.md`. Este guia pode aparecer como alterado até o usuário commitá-lo; pergunte se ele
  quer fazer isso antes de começar.
- O código ainda usa o Google ADK em `web/backend/chat.py`. A troca descrita abaixo ainda não foi
  feita.
- Rodando localmente: o frontend em `localhost:3000` e o backend em `localhost:8000`.
- **Conta de teste:** peça ao usuário. Não escreva a senha em nenhum arquivo.

## Arquitetura

Alvo, depois da troca do ADK:

```
navegador ──> web/frontend (Next.js 16.4, React 19)   ──fetch, credentials: "include"──>
              web/backend  (FastAPI, Python)           ──> Supabase (Auth + Postgres)
                                                       ──> proxy LiteLLM (Felicia, via httpx)
```

### Frontend: `web/frontend/`

- `npm run build` e `npm start`. A Vercel detecta Next.js sozinha; o **Root Directory** do
  projeto deve ser `web/frontend`.
- Única variável: `NEXT_PUBLIC_API_URL`. O padrão é `http://localhost:8000` e está definido em
  `app/dashboard/formato.tsx`. Ela também é lida em `app/login/page.tsx`,
  `app/cadastro/page.tsx` e `app/felicia-chat.tsx`.
- `proxy.ts` (o "middleware" do Next 16) redireciona `/` para `/login` quando não encontra os
  cookies `inflatrack_access_token` ou `inflatrack_refresh_token`.
- `next.config.ts` usa opções experimentais (`agentFeedback`, `cacheComponents`,
  `partialPrefetching`). Confira se o build passa na Vercel com elas.
- Leia `web/frontend/AGENTS.md` antes de mexer no frontend.

### Backend: `web/backend/`

- FastAPI em `app.py`, que também define a rota `POST /chat` e as 3 ferramentas da Felicia
  (`consultar_inflacao`, `buscar_produto` e `prever_reajuste`). Os outros arquivos são `chat.py`
  (a conversa com o modelo), `publicacao.py` (leitura das tabelas publicadas), `database.py`
  (SQLAlchemy + psycopg), `migrations/001..004_*.sql` e `tests/`.
- Dependências em `requirements.txt`: fastapi, uvicorn, SQLAlchemy, psycopg[binary], httpx,
  email-validator, python-dotenv e, **hoje**, google-adk e litellm. Os dois últimos são pacotes
  muito grandes e **saem na troca** descrita na seção "Felicia". Sem eles, o backend fica leve, e
  isso muda o peso da decisão 1.
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
relativa funciona em todos os pontos que leem `NEXT_PUBLIC_API_URL` (lista na seção do frontend).
A Felicia não usa streaming: a resposta de `POST /chat` é um JSON único.

A alternativa (`samesite="none"` + `secure` + domínio próprio com subdomínios) é mais frágil.
Só use se o usuário pedir.

## Felicia: trocar o Google ADK por chamadas diretas ao proxy (decidido)

Hoje `web/backend/chat.py` usa o Google ADK, que passa pela biblioteca Python `litellm` para
chegar ao proxy LiteLLM. Isso causa dois problemas para o deploy, e a troca resolve os dois:

- **Tamanho:** só para o chat são cerca de 245 MB instalados (`litellm` 199 MB, `google/adk` 31 MB
  e `google/genai` 15 MB, medidos no `.venv` em 2026-11-24). Isso aperta ou estoura o limite de
  uma função Python na Vercel.
- **Histórico:** `InMemorySessionService` guarda a conversa na memória do processo. Em serverless
  cada requisição pode cair numa instância nova, e a Felicia esquece o que foi dito no meio da
  conversa. Com o histórico no navegador (decisão 2), o servidor não precisa lembrar de nada.

**Teste feito em 2026-11-24** (script descartável, chaves lidas do `.env` sem imprimir) mostrou que
o proxy aguenta o laço de ferramentas sem a biblioteca:

- `POST {LITELLM_PROXY_URL}/v1/chat/completions` no formato da OpenAI, com `tools`, respondeu
  HTTP 200 em cerca de 4 s. O modelo pediu `consultar_inflacao({"praca":"Brasil"})`.
- A 2ª rodada, que devolve o resultado com `role: "tool"`, respondeu HTTP 200 em cerca de 3 s com o
  texto final correto. **O laço de ferramentas funciona direto no proxy.**
- **Atenção ao nome do modelo:** `LITELLM_MODEL=openai/gpt-5.4-mini` dá **403** direto no proxy.
  O prefixo `openai/` é uma convenção da biblioteca `litellm`, que o remove antes de chamar. Direto
  no proxy, o nome é `gpt-5.4-mini`.
- `GET /v1/models` respondeu 503 "App port is not ready" nesse momento, o que indica que o proxy
  pode ter partida a frio (cold start). Trate timeout e erro com uma mensagem amigável.

**O que implementar:**

1. **Backend, `chat.py`.** Reescreva com `httpx` (já é dependência): envie as instruções da Felicia
   (`INSTRUCAO`), o histórico recebido e as 3 ferramentas descritas em JSON Schema (o ADK as
   deduzia das funções Python, então agora o esquema precisa ser escrito à mão). Execute as
   `tool_calls`, devolva `role: "tool"` e repita, com no máximo 5 rodadas. Remova o `_sessoes`, o
   `Runner` e tudo o que for do ADK.
2. **Modelo.** Sem o `litellm`, o prefixo `openai/` não serve mais. Troque o valor em
   `.env.example` e o padrão no código por `gpt-5.4-mini`, e avise o usuário para ajustar o próprio
   `.env` (não imprima o conteúdo dele).
3. **Backend, `app.py`.** As funções `consultar_inflacao`, `buscar_produto` e `prever_reajuste`
   continuam iguais. No `ChatRequest`, tire o `session_id` e acrescente `history`: no máximo 10
   itens, com `role` restrito a `user` e `assistant` e `text` limitado em tamanho (o `message`
   atual já aceita até 2000 caracteres). O modelo tem `extra="forbid"`, então o frontend e o
   backend precisam mudar juntos.
4. **Frontend, `felicia-chat.tsx`.** O componente já guarda `messages` em estado, então basta
   enviar no `POST /chat` as **10 últimas mensagens anteriores** à pergunta nova, em
   `history`. Não envie a saudação inicial, que é só do frontend. Apague o `sessionId`.
5. **Dependências.** Remova `google-adk` e `litellm` do `requirements.txt`.
6. **Testes** em `web/backend/tests` com o `httpx` simulado (MockTransport), escritos antes do
   código, como no restante do projeto: resposta direta, uma ferramenta, várias rodadas, limite de
   rodadas, erro do proxy e rejeição de `history` inválido (mais de 10 itens, papel `tool` ou
   `system`).

## Decisões para levar ao usuário

Pergunte com contexto, conforme as regras acima, e não decida sozinho. Faça a troca do ADK antes
(passo 3 do plano) para poder medir o tamanho real do backend e levar o número junto da pergunta 1.

1. **Onde roda o backend FastAPI.**
   - (a) Na Vercel, como função Python, em outro projeto ou no mesmo repositório. É grátis e fica
     num lugar só, mas tem limite de tamanho do pacote e de tempo por requisição. Sem o ADK e o
     litellm o tamanho deixa de ser problema, mas o chat ainda pode passar do tempo: o laço de
     ferramentas pode chegar a 5 rodadas de 3 a 4 s, e o proxy pode ter partida a frio. Meça.
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
3. Faça a troca do ADK e o histórico no navegador, conforme a seção "Felicia" (decisões já
   tomadas). Rode os testes de novo e confirme que o chat funciona localmente. Depois, instale o
   `requirements.txt` num ambiente limpo e meça o tamanho.
4. Leve as decisões 1–4 ao usuário, com o tamanho medido no passo 3.
5. Implemente o rewrite `/api` e ajuste `NEXT_PUBLIC_API_URL`. Teste localmente com
   `npm run build && npm start`, apontando para o backend local.
6. Prepare a configuração do backend escolhido (por exemplo `vercel.json` ou `api/index.py` para a
   Vercel, ou `Dockerfile`/`render.yaml`) e um `.env.example` com todas as variáveis de produção.
   Em produção, `COOKIE_SECURE=true`.
7. Escreva `docs/como_rodar/deploy_vercel.md` com o passo a passo, para o grupo repetir o deploy.
8. Com confirmação do usuário: crie os projetos, configure as variáveis, faça o deploy e ajuste as
   URLs no Supabase Auth.
9. Valide em produção: cadastro, login, dashboard de Brasil e de uma praça, troca de abas, uma
   conversa com a Felicia de mais de uma pergunta (para conferir que o histórico chega) e logout.
   Teste em largura de celular também.

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
- O `requirements.txt` não tem mais `google-adk` nem `litellm`, e a Felicia responde usando o
  histórico enviado pelo navegador (no máximo 10 mensagens anteriores).
- Login, dashboard e Felicia funcionam na URL pública, com cookies `Secure`.
- Nenhum segredo está no repositório.
- `docs/como_rodar/deploy_vercel.md` existe, e o `AI-USAGE.md` foi atualizado.
