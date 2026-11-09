begin;

create table if not exists public.profiles (
    user_id uuid primary key references auth.users (id) on delete cascade,
    email text,
    full_name text,
    created_at timestamptz not null default now()
);

create unique index if not exists profiles_email_unique_idx
    on public.profiles (lower(email))
    where email is not null;

alter table public.profiles enable row level security;
revoke all on public.profiles from anon, authenticated;
grant select on public.profiles to authenticated;

drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own
    on public.profiles
    for select
    to authenticated
    using ((select auth.uid()) = user_id);

create or replace function public.sync_auth_user_profile()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.profiles (user_id, email, full_name)
    values (new.id, new.email, new.raw_user_meta_data ->> 'full_name')
    on conflict (user_id) do update
        set email = excluded.email,
            full_name = excluded.full_name;

    return new;
end;
$$;

drop trigger if exists on_auth_user_created_profile on auth.users;
create trigger on_auth_user_created_profile
    after insert on auth.users
    for each row execute function public.sync_auth_user_profile();

insert into public.profiles (user_id, email, full_name)
select id, email, raw_user_meta_data ->> 'full_name'
from auth.users
on conflict (user_id) do update
    set email = excluded.email,
        full_name = excluded.full_name;

commit;