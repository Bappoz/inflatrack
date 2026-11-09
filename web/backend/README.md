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

O frontend usa `NEXT_PUBLIC_API_URL` para localizar a API; sem essa variável,
usa `http://localhost:8000`. Configure `CORS_ORIGINS` com as origens reais do
frontend em cada ambiente.

`POST /auth/register` recebe `name`, `email`, `password` e `confirm_password`.
O endpoint nunca retorna tokens do Supabase. A chave secreta não é necessária
para cadastro e não deve ser adicionada ao frontend.

## Tabela de perfis no Supabase

O Supabase Auth mantém as credenciais em `auth.users`. Para também visualizar
os dados de perfil no Table Editor, execute `migrations/001_profiles.sql` uma
vez em **Supabase Dashboard → SQL Editor**. A migration cria `public.profiles`,
preenche os usuários que já existem e instala um trigger para novos cadastros.
O `user_id` é a chave primária ligada a `auth.users.id`; o e-mail tem índice
único sem distinção entre maiúsculas e minúsculas. Senhas não são copiadas para
essa tabela.