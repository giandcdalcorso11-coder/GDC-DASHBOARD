-- Tipologie personalizzate (nome + emoji) per la pagina Macchina di GDC STUDIO.
create table public.studio_hardware_types (
  id bigint primary key,
  user_id uuid not null default auth.uid(),
  nome text not null,
  emoji text not null,
  updated_at timestamptz default now()
);
alter table public.studio_hardware_types enable row level security;
create policy "own hardware types" on public.studio_hardware_types for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
