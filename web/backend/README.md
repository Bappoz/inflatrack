# Inflatrack Auth API

API Python/FastAPI com Supabase Auth para autenticação e SQLAlchemy para
persistência dos dados dos usuários no PostgreSQL do Supabase.

## Executar localmente

Execute os comandos abaixo na raiz do repositório, com Python 3.12 ou superior:

```bash
python3.12 -m venv web/backend/.venv
source web/backend/.venv/bin/activate
python -m pip install -e . -r web/backend/requirements.txt
```

A instalação com `-e .` inclui o pacote local `inflatrack` e suas dependências,
necessários para importar os helpers de banco usados pela API.

Se `web/backend/.env` ainda não existir, copie `web/backend/.env.example` para
esse caminho. Configure:

- `SUPABASE_URL` e `SUPABASE_PUBLISHABLE_KEY`: autenticação.
- `DATABASE_URL`: conexão PostgreSQL usada pelo SQLAlchemy para `public.users`.
- `DIRECT_URL`: conexão direta ou session pooler para aplicar o esquema.

As duas conexões devem apontar para o mesmo projeto do Supabase Auth. URLs
`postgres://` e `postgresql://` usam o driver Psycopg 3. O parâmetro `pgbouncer`
de URLs copiadas do Prisma é removido antes de conectar; prepared statements
ficam desativados e o pool de conexões é delegado ao Supabase. Recomenda-se
`sslmode=require` nas URLs do Supabase. Nunca coloque essas URLs no frontend.

Depois, entre na pasta do backend, aplique o esquema uma vez e inicie a API:

```bash
cd web/backend
.venv/bin/python database.py
.venv/bin/python -m uvicorn app:app --reload --port 8000
```

O comando `database.py` usa exclusivamente `DIRECT_URL`. Pode ser repetido após
atualizações do script de esquema; não apaga os usuários existentes.
Para parar a API, use **Ctrl+C** (Ctrl+Z apenas suspende o processo).

O login cria cookies de sessão `HttpOnly`; em produção com HTTPS, defina `COOKIE_SECURE=true`.

O frontend chama a API pelo próprio domínio, em `/api`, e o Next repassa para
`BACKEND_URL` (padrão `http://localhost:8000`). Assim os cookies ficam no domínio
do site. Configure `CORS_ORIGINS` com as origens reais do frontend em cada
ambiente. O deploy está em `docs/como_rodar/deploy_vercel.md`.

`POST /auth/register` recebe `name`, `email`, `state` (sigla da UF), `password`
e `confirm_password`. O cadastro verifica a disponibilidade da tabela antes de
chamar o Supabase Auth e grava nome, e-mail e estado com SQLAlchemy, usando o
UUID do Auth como vínculo. A gravação é um upsert por `user_id`, compatível com
os triggers já existentes. Nome e estado continuam nos metadados do Auth.
O endpoint nunca retorna tokens nem salva senhas em `public.users`.

Se a conexão falhar depois da criação no Auth, a API retorna erro explícito
informando que a conta já foi criada, em vez de indicar sucesso ou recriá-la.
Reaplique o esquema após restaurar a conexão para sincronizar os metadados.
O cadastro HTTP no Auth e o upsert da API não formam uma única transação;
os triggers mantêm a cópia inicial atômica no banco do Supabase.

O dashboard continua usando o PostgreSQL analítico local, configurado pelas
variáveis `POSTGRES_*`; `DATABASE_URL` não muda a origem dos seus indicadores.

## Tabela `public.users` no Supabase

O Supabase Auth mantém as credenciais em `auth.users`. O comando `database.py`
aplica [`migrations/002_users.sql`](migrations/002_users.sql) via SQLAlchemy.
Não há criação automática de tabelas ao iniciar o servidor.

Como alternativa, aplique o mesmo script pelo navegador:

1. Abra o mesmo projeto configurado em `SUPABASE_URL` no Supabase Dashboard.
2. Em **SQL Editor → New query**, cole o conteúdo completo de
   [`migrations/002_users.sql`](migrations/002_users.sql) e execute com **Run**.
   O script pode ser reexecutado se a tabela já existir.
3. Em **Table Editor**, selecione o schema `public` e a tabela `users`.

O script cria `public.users`, adiciona a coluna `state`, preenche os usuários
já existentes e instala triggers para sincronizar novos cadastros e alterações
de e-mail/nome/estado na mesma transação do Supabase Auth. Usuários antigos
sem estado nos metadados ficam com `state` nulo. O e-mail é a chave primária e tem unicidade sem distinção entre
maiúsculas e minúsculas; `user_id` referencia `auth.users.id`. Senhas nunca são
copiadas para `public.users`.

Para conferir a sincronização sem exibir dados pessoais, execute no SQL Editor:

```sql
select
    (select count(*) from auth.users where email is not null) as usuarios_auth,
    (select count(*) from public.users) as usuarios_publicos,
    (
        select count(*)
        from auth.users a
        left join public.users u on u.user_id = a.id
        where a.email is not null
          and (
              u.user_id is null
              or u.email is distinct from lower(a.email)
              or u.name is distinct from coalesce(
                  nullif(btrim(a.raw_user_meta_data ->> 'full_name'), ''),
                  split_part(lower(a.email), '@', 1)
              )
              or u.state is distinct from a.raw_user_meta_data ->> 'state'
          )
    ) as usuarios_nao_sincronizados;
```

O resultado esperado é `usuarios_nao_sincronizados = 0`.

`migrations/001_profiles.sql` continua disponível para projetos que também
queiram a tabela `public.profiles`; ela não é alterada por `002_users.sql`.