-- Step 11 (ruoli e permessi per collaboratori: osservatore/operatore per area) — applicata su Supabase il 19/11/2026.
-- Registro, non eseguito automaticamente (vedi nota in 20261114_add_posts_categorization.sql).

-- Una riga per account Supabase Auth. is_admin è solo per Gianluca: accesso
-- operatore automatico ovunque (su entrambe le aree) + unico che vede la
-- pagina di amministrazione. ia_team_ruolo/studio_ruolo sono indipendenti
-- tra loro (una persona può essere operatore su un'area e osservatore
-- sull'altra) e vengono letti solo quando is_admin è false.
create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text,
  is_admin boolean not null default false,
  ia_team_ruolo text not null default 'nessuno' check (ia_team_ruolo in ('nessuno','osservatore','operatore')),
  studio_ruolo text not null default 'nessuno' check (studio_ruolo in ('nessuno','osservatore','operatore')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.profiles is 'Ruoli/permessi per collaboratori (Step 11). is_admin implica operatore su entrambe le aree a prescindere da ia_team_ruolo/studio_ruolo.';
comment on column public.profiles.is_admin is 'Solo Gianluca. Accesso operatore automatico ovunque + unico che vede la pagina di amministrazione (Impostazioni -> Account).';
comment on column public.profiles.ia_team_ruolo is 'Ruolo su GDC IA TEAM: nessuno/osservatore/operatore. Ignorato se is_admin=true.';
comment on column public.profiles.studio_ruolo is 'Ruolo su GDC Studio: nessuno/osservatore/operatore. Ignorato se is_admin=true.';

-- Helper SECURITY DEFINER per evitare la ricorsione RLS nelle policy sotto
-- (una policy su profiles non può interrogare profiles direttamente sotto RLS).
create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select coalesce((select is_admin from public.profiles where user_id = auth.uid()), false);
$$;

-- Risolve il ruolo effettivo dell'utente corrente per una delle due aree
-- ('ia_team' | 'studio'), tenendo conto che is_admin vale 'operatore' ovunque.
-- Pensata per essere chiamata dalle pagine via RPC per decidere cosa abilitare.
create or replace function public.current_user_role(area text)
returns text
language sql
stable
security definer
set search_path = public
as $$
  select case
    when (select is_admin from public.profiles where user_id = auth.uid()) then 'operatore'
    when area = 'ia_team' then coalesce((select ia_team_ruolo from public.profiles where user_id = auth.uid()), 'nessuno')
    when area = 'studio' then coalesce((select studio_ruolo from public.profiles where user_id = auth.uid()), 'nessuno')
    else 'nessuno'
  end;
$$;

alter table public.profiles enable row level security;

-- Chiunque sia autenticato può leggere tutti i profili: serve sia alla pagina
-- di amministrazione (elenco account) sia a ogni pagina per risolvere il
-- proprio ruolo — stesso pattern "authenticated read: true" già in uso su
-- companies/agent_states.
create policy "authenticated read" on public.profiles for select using (true);

-- Solo l'admin può modificare permessi (propri o altrui). Nessun self-service:
-- un utente normale non può toccare la propria riga (coerente con "solo
-- gestione permessi su account già esistenti", niente auto-promozione).
create policy "admin manages profiles" on public.profiles for update using (public.is_admin()) with check (public.is_admin());

-- Creazione automatica della riga quando Gianluca crea un nuovo account
-- Supabase Auth altrove (dashboard) — niente flusso di invito via email.
create or replace function public.handle_new_user_profile()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (user_id, email)
  values (new.id, new.email)
  on conflict (user_id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created_profile
  after insert on auth.users
  for each row execute function public.handle_new_user_profile();

-- Seed: l'unico account esistente oggi (Gianluca) diventa admin.
insert into public.profiles (user_id, email, is_admin)
select id, email, true from auth.users
on conflict (user_id) do update set is_admin = true;
