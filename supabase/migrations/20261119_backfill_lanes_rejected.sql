-- Step 10 ("pipeline a rami" su page_company_v2.html) — applicata su Supabase il 19/11/2026.
-- Registro, non eseguito automaticamente (vedi nota in 20261114_add_posts_categorization.sql).

-- Le aziende che erano già a step_attuale=13 col vecchio meccanismo (quello
-- col bug: segnava anche tutti gli step precedenti come fatti) vanno
-- migrate al nuovo modello indipendente: rejected=true, e lo step_attuale
-- riportato a 4 (il bivio) così la UI non mostra una pipeline falsamente
-- completata fino al 12.
update public.companies
set rejected = true, step_attuale = 4
where step_attuale = 13;

-- instagram_stato/linkedin_stato (vecchio modello a singolo canale) diventano
-- il primo ramo "legacy" dentro lanes, per non perdere lo storico esistente.
-- (Lo stage e il colore derivano dal valore testuale di *_stato; l'evento
-- "legacy" riporta la data di primo contatto se presente.)
update public.companies
set lanes = lanes || jsonb_build_array(
  jsonb_build_object(
    'id', 'instagram',
    'label', 'Instagram',
    'short', 'IG',
    'color', 'var(--life)',
    'stage', case instagram_stato
      when 'contattato' then 1
      when 'risposta' then 2
      when 'gestita' then 4
      else 0
    end,
    'events', jsonb_build_array(
      jsonb_build_array(jsonb_build_object('date', 'legacy', 'text', coalesce(instagram_stato, ''))),
      '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb
    )
  )
)
where instagram_stato is not null;

update public.companies
set lanes = lanes || jsonb_build_array(
  jsonb_build_object(
    'id', 'linkedin',
    'label', 'LinkedIn',
    'short', 'LI',
    'color', 'var(--athlete)',
    'stage', case linkedin_stato
      when 'contattato' then 1
      when 'risposta' then 2
      when 'gestita' then 4
      else 0
    end,
    'events', jsonb_build_array(
      jsonb_build_array(jsonb_build_object('date', 'legacy', 'text', coalesce(linkedin_stato, ''))),
      '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb
    )
  )
)
where linkedin_stato is not null;
