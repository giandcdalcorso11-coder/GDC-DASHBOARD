-- Step 5 (copertine reali dei post, invece del placeholder colorato) — applicata su Supabase il 15/11/2026.
-- Registro, non eseguito automaticamente (vedi nota in 20261114_add_posts_categorization.sql).

-- Bucket pubblico per le copertine: A1 scarica l'immagine da Instagram
-- (media_url/thumbnail_url, firmati e che scadono) e la ri-ospita qui in
-- modo permanente. Lettura pubblica necessaria perché <img src> non manda
-- header di autenticazione.
insert into storage.buckets (id, name, public) values ('post-covers', 'post-covers', true)
on conflict (id) do nothing;

-- URL pubblico della copertina, scritto da a1_monthly.py insieme al resto
-- del post. Nullo per i REPOST (nessun accesso ai media di altri account)
-- e per gli ORIGINALE il cui download/upload è temporaneamente fallito.
alter table public.posts add column image_url text;
