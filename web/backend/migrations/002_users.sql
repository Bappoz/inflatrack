begin;

create table if not exists public.users (
    email text primary key,
    user_id uuid not null unique references auth.users (id) on delete cascade,
    name text not null,
    created_at timestamptz not null default now()
);

alter table public.users
    add column if not exists state text check (
        state in (
            'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO',
            'MA', 'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI',
            'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO'
        )
    );

create unique index if not exists users_email_lower_unique_idx
    on public.users (lower(email));

alter table public.users enable row level security;
revoke all on public.users from anon, authenticated;
grant select on public.users to authenticated;

drop policy if exists users_select_own on public.users;
create policy users_select_own
    on public.users
    for select
    to authenticated
    using ((select auth.uid()) = user_id);

create or replace function public.sync_auth_user_to_public_users()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    normalized_email text;
    display_name text;
begin
    if new.email is null then
        return new;
    end if;

    normalized_email := lower(new.email);
    display_name := coalesce(
        nullif(btrim(new.raw_user_meta_data ->> 'full_name'), ''),
        split_part(normalized_email, '@', 1)
    );

    insert into public.users (user_id, email, name, state)
    values (new.id, normalized_email, display_name, new.raw_user_meta_data ->> 'state')
    on conflict (user_id) do update
        set email = excluded.email,
            name = excluded.name,
            state = excluded.state;

    return new;
end;
$$;

drop trigger if exists on_auth_user_created_public_user on auth.users;
create trigger on_auth_user_created_public_user
    after insert on auth.users
    for each row execute function public.sync_auth_user_to_public_users();

drop trigger if exists on_auth_user_updated_public_user on auth.users;
create trigger on_auth_user_updated_public_user
    after update of email, raw_user_meta_data on auth.users
    for each row execute function public.sync_auth_user_to_public_users();

insert into public.users (user_id, email, name, state)
select
    id,
    lower(email),
    coalesce(
        nullif(btrim(raw_user_meta_data ->> 'full_name'), ''),
        split_part(lower(email), '@', 1)
    ),
    raw_user_meta_data ->> 'state'
from auth.users
where email is not null
on conflict (user_id) do update
    set email = excluded.email,
        name = excluded.name,
        state = excluded.state;

commit;