-- Step 10 ("pipeline a rami" su page_company_v2.html) — applicata su Supabase il 19/11/2026.
-- Registro, non eseguito automaticamente (vedi nota in 20261114_add_posts_categorization.sql).

-- Rami della pipeline a rami (Instagram, LinkedIn, rami manuali) — array di
-- {id,label,short,color,stage,events[5]}. Il ramo Mail NON è qui: resta "a
-- ponte" con step_5..step_9/step_notes per non rompere automazione A6/A7.
alter table public.companies add column lanes jsonb not null default '[]'::jsonb;
comment on column public.companies.lanes is 'Rami della pipeline a rami (Instagram, LinkedIn, rami manuali) — array di {id,label,short,color,stage,events[5]}. Il ramo Mail NON è qui: resta "a ponte" con step_5..step_9/step_notes per non rompere automazione A6/A7.';

-- Storico eventi extra per gli step 1-4/10-13 del tronco, keyed per numero
-- di step (testo). Si aggiunge alla nota singola legacy step_notes[N], non
-- la sostituisce.
alter table public.companies add column trunk_events jsonb not null default '{}'::jsonb;
comment on column public.companies.trunk_events is 'Storico eventi extra per gli step 1-4/10-13 del tronco, keyed per numero di step (testo). Si aggiunge alla nota singola legacy step_notes[N], non la sostituisce.';

-- Step 13 "Rifiutato", indipendente da step_attuale (fix bug: prima settare
-- rifiutato segnava per errore come "fatti" tutti gli step precedenti).
alter table public.companies add column rejected boolean not null default false;
comment on column public.companies.rejected is 'Step 13 "Rifiutato", indipendente da step_attuale (fix bug: prima settare rifiutato segnava per errore come "fatti" tutti gli step precedenti).';
