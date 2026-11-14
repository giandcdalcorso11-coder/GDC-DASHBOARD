-- Step 5 (dashboard A2 — grafici mese per mese) — applicata su Supabase il 14/11/2026.
-- Registro, non eseguito automaticamente (vedi nota in 20261114_add_posts_categorization.sql).

-- KPI medi mensili, già calcolati da a1_monthly.py per lo Sheet 4 "KPI Medi"
-- dell'Excel — nessun calcolo duplicato, solo sincronizzazione dei valori già
-- prodotti. Letta dalla dashboard A2 per i grafici mese per mese.
create table public.kpi_mensili (
  mese text primary key,               -- es. "Ottobre 2026" (stessa label dello Sheet 4)
  anno integer not null,
  mese_num integer not null,           -- 1-12, per ordinamento cronologico
  er_medio numeric,
  viz_medie_post numeric,
  reach_medio_post numeric,
  like_medio numeric,
  commenti_medi numeric,
  salvataggi_medi numeric,
  tasso_viralita_medio numeric,
  sentiment_score_medio numeric,
  viz_medie_stories numeric,
  reach_medio_stories numeric,
  updated_at timestamptz not null default now()
);

alter table public.kpi_mensili enable row level security;
create policy "authenticated_all_kpi_mensili" on public.kpi_mensili for all to authenticated using (true) with check (true);
