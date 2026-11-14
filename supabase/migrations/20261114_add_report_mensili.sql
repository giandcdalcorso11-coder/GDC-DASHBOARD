-- Step 5 (report HTML di A2/A3/A4, invece di pptx/pdf) — applicata su Supabase il 14/11/2026.
-- Registro, non eseguito automaticamente (vedi nota in 20261114_add_posts_categorization.sql).

-- Tabella condivisa per i report mensili dei 3 agenti (agente a2/a3/a4): ogni
-- agente scrive la propria pagina HTML completa (autonoma, con il proprio
-- <style>) tramite il connector MCP Supabase GDC, al posto di generare un
-- file pptx/pdf. La webapp la mostra dentro un iframe (report.html), così lo
-- stile del report resta isolato da quello dell'app.
create table public.report_mensili (
  agente text not null check (agente in ('a2','a3','a4')),
  mese text not null,                  -- es. "Ottobre 2026"
  anno integer not null,
  mese_num integer not null,           -- 1-12, per ordinamento cronologico
  html text not null,                  -- pagina HTML completa e autonoma
  updated_at timestamptz not null default now(),
  primary key (agente, mese)
);

create index report_mensili_agente_idx on public.report_mensili (agente, anno, mese_num);

alter table public.report_mensili enable row level security;
create policy "authenticated_all_report_mensili" on public.report_mensili for all to authenticated using (true) with check (true);
