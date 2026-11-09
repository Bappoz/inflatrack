# Inflatrack Auth API

API Python que cria usuários pelo endpoint de signup do Supabase Auth.

## Executar localmente

```bash
python -m venv web/backend/.venv
source web/backend/.venv/bin/activate
pip install -r web/backend/requirements.txt
cp web/backend/.env.example web/backend/.env
```

Preencha `SUPABASE_URL` e `SUPABASE_PUBLISHABLE_KEY` no `.env` e inicie a API:

```bash
uvicorn web.backend.app:app --reload --port 8000
```

O login cria cookies de sessão `HttpOnly`; em produção com HTTPS, defina `COOKIE_SECURE=true`.

O frontend usa `NEXT_PUBLIC_API_URL` para localizar a API; sem essa variável,
usa `http://localhost:8000`. Configure `CORS_ORIGINS` com as origens reais do
frontend em cada ambiente.

`POST /auth/register` recebe `name`, `email`, `password` e `confirm_password`.
O endpoint nunca retorna tokens do Supabase. A chave secreta não é necessária
para cadastro e não deve ser adicionada ao frontend.

## Tabela `public.users` no Supabase

O Supabase Auth mantém as credenciais em `auth.users`. Para visualizar os
cadastros como tabela pública, execute `migrations/002_users.sql` uma vez em
**Supabase Dashboard → SQL Editor**. Ela cria `public.users`, preenche usuários
já existentes e instala triggers para sincronizar novos cadastros e alterações
de e-mail/nome. O e-mail é a chave primária e tem unicidade sem distinção entre
maiúsculas e minúsculas; `user_id` referencia `auth.users.id`. Senhas nunca são
copiadas para `public.users`.

`migrations/001_profiles.sql` continua disponível para projetos que também
queiram a tabela `public.profiles`; ela não é alterada por `002_users.sql`.