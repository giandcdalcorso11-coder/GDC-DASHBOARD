#!/usr/bin/env python3
"""
GDC IA TEAM — A1 MBS Watcher

Controllo periodico leggero: se il CSV MBS repost manca ancora (flag
mbs_missing attivo su Supabase), ricontrolla se nel frattempo è stato
caricato su Supabase Storage (bucket mbs-csv, via webapp — vedi
app/agenti/a1-analytics/carica_mbs.html) e, in tal caso, ritriggera A1
Monthly via GitHub API — così Gianluca vede il foglio aggiornarsi da
solo, senza rilanciare nulla a mano.

Gira SOLO dal giorno 2 al giorno 10 del mese, ogni 30 minuti (cron nel
workflow a1_mbs_watcher.yml). Fuori da questa finestra il workflow non
parte proprio: zero run, zero rumore nello storico Actions.

GitHub Actions non supporta run in pausa indefinita in attesa di un
evento esterno (limite 6h sui runner standard) — questo script è la
soluzione: un controllo leggero e periodico, non un'attesa attiva.

Vedi step 20, sezione 3.10. Aggiornato il 16/11/2026: il controllo era
su Drive ("Archivio docs MBS"), ora e' su Supabase Storage — non serve
piu' l'accesso a Google Drive, quindi GOOGLE_CREDENTIALS non e' piu'
richiesto da questo script.

Variabili d'ambiente richieste:
  SUPABASE_URL / SUPABASE_SERVICE_KEY  (service_role: bypassa la RLS, mai l'anon key)
  GH_PAT_REPO         — Personal Access Token scope 'repo' (già usato da ig_token_refresh.py
                         per scrivere i GitHub Secrets — stesso PAT, scope sufficiente
                         anche per attivare un workflow_dispatch)
"""

import os
import requests
from supabase import create_client

SUPA_URL = os.environ["SUPABASE_URL"]
SUPA_KEY = os.environ["SUPABASE_SERVICE_KEY"]  # service_role: bypassa la RLS, mai l'anon key
GH_PAT   = os.environ["GH_PAT_REPO"]

GH_OWNER = "giandcdalcorso11-coder"
GH_REPO  = "GDC-DASHBOARD"

MBS_BUCKET = "mbs-csv"  # stesso bucket usato da a1_monthly.py (find_mbs_csv_path)

MESE_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"
]


def parse_mese_label(mese_label):
    """'Giugno 2026' -> (6, 2026). None se il formato non è riconosciuto."""
    try:
        mese_str, anno_str = mese_label.strip().split()
        mese_num = MESE_IT.index(mese_str.lower()) + 1
        return mese_num, int(anno_str)
    except (ValueError, AttributeError):
        return None


def find_mbs_csv_path(supabase, mese_num, anno):
    """
    Stessa identica logica di find_mbs_csv_path() in a1_monthly.py, ma
    parametrizzata su mese/anno invece che sul mese target implicito
    (qui il "mese target" arriva dal flag Supabase, non da oggi-1mese).
    """
    path = f"{anno}-{mese_num:02d}.csv"
    files = supabase.storage.from_(MBS_BUCKET).list()
    names = {f.get("name") for f in files}
    return path if path in names else None


def trigger_a1_monthly():
    """Ritrigger di a1_monthly.yml via GitHub API workflow_dispatch —
    stesso meccanismo (lato codice) del tasto 'Avvia Run Manuale' in
    dashboard, ma automatico."""
    url = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/actions/workflows/a1_monthly.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json"
    }
    resp = requests.post(url, headers=headers, json={"ref": "main"})
    resp.raise_for_status()
    print("    → a1_monthly.yml ritriggerato via workflow_dispatch")


def main():
    supabase = create_client(SUPA_URL, SUPA_KEY)
    res = supabase.table("agent_states").select(
        "mbs_missing,mbs_missing_mese"
    ).eq("agent_id", "a1").execute()

    if not res.data or not res.data[0].get("mbs_missing"):
        print("Flag mbs_missing non attivo — niente da fare, esco.")
        return

    mese_label = res.data[0].get("mbs_missing_mese")
    parsed = parse_mese_label(mese_label) if mese_label else None
    if not parsed:
        print(f"⚠ mbs_missing_mese non valido o mancante ({mese_label!r}) — esco.")
        return

    mese_num, anno = parsed
    print(f"Flag attivo per {mese_label} — controllo il bucket Storage '{MBS_BUCKET}'...")

    path = find_mbs_csv_path(supabase, mese_num, anno)

    if not path:
        print(f"    Ancora nessun CSV per {mese_label} — riprovo al prossimo giro (30 min).")
        return

    print(f"    ✅ CSV trovato per {mese_label} — ritriggero A1 Monthly")
    trigger_a1_monthly()
    # NB: il flag Supabase e l'email di conferma "repost recuperati" vengono
    # gestiti da a1_monthly.py stesso, al termine della run appena
    # triggerata (vedi fetch_mbs_reposts() — step 20, 3.9/3.10). Non li
    # tocchiamo qui: se la run fallisse per un altro motivo, il flag deve
    # restare attivo per riprovare al giro successivo.


if __name__ == "__main__":
    main()
