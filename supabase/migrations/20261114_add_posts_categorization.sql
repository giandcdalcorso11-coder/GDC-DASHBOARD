-- Step 4 (schermata di categorizzazione post) — applicata su Supabase il 14/11/2026.
-- Questo file è un registro, non viene eseguito automaticamente: non esiste
-- ancora nel progetto un flusso di migrazioni applicate da CI/script. Se in
-- futuro se ne adotta uno, questo è il punto di partenza.

-- Post Instagram ORIGINALE (i REPOST non si categorizzano, restano solo su Excel).
-- Scritta da a1_monthly.py (service_role) e letta/modificata dalla webapp
-- (schermata di categorizzazione, autenticata).
create table public.posts (
  id text primary key,                 -- IG media id
  mese text not null,
  data text,
  ora text,
  tipo_contenuto text,
  caption text,
  categoria_primaria text check (categoria_primaria is null or categoria_primaria = any(array['SPORT','RELATION','GDC STUFF','DIVULGAZIONE'])),
  categoria_secondaria text,
  permalink text,
  episodio_serie integer,
  updated_at timestamptz not null default now()
);

create index posts_mese_idx on public.posts (mese);

alter table public.posts enable row level security;
create policy "authenticated_all_posts" on public.posts for all to authenticated using (true) with check (true);

-- Vocabolario categorie secondarie: cresce quando Gianluca inserisce testo
-- libero dalla schermata di categorizzazione, non si fraziona in varianti.
create table public.categoria_secondaria_vocabolario (
  id bigint generated always as identity primary key,
  categoria_primaria text not null,
  valore text not null,
  created_at timestamptz not null default now(),
  unique (categoria_primaria, valore)
);

alter table public.categoria_secondaria_vocabolario enable row level security;
create policy "authenticated_all_categoria_secondaria_vocabolario" on public.categoria_secondaria_vocabolario for all to authenticated using (true) with check (true);

insert into public.categoria_secondaria_vocabolario (categoria_primaria, valore) values
  ('SPORT', 'Torneo/Gara'),
  ('SPORT', 'Allenamento'),
  ('SPORT', 'Nazionale'),
  ('SPORT', 'Viaggio/Trasferta'),
  ('RELATION', 'Coppia'),
  ('RELATION', 'Famiglia'),
  ('RELATION', 'Amici'),
  ('GDC STUFF', 'Stampa 3D'),
  ('GDC STUFF', 'Elettronica/Coding'),
  ('GDC STUFF', 'Prodotto finito'),
  ('GDC STUFF', 'Making of'),
  ('DIVULGAZIONE', 'GDC STUFF');

-- Colonne per il suggerimento AI, non ancora popolate da nessun processo:
-- pronte per quando la sessione Claude Code dedicata (Step 8) le scriverà.
alter table public.posts
  add column categoria_primaria_suggerita text check (categoria_primaria_suggerita is null or categoria_primaria_suggerita = any(array['SPORT','RELATION','GDC STUFF','DIVULGAZIONE'])),
  add column categoria_secondaria_suggerita text;
