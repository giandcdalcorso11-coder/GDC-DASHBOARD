#!/usr/bin/env python3
"""
GDC IA TEAM — A1 MBS Watcher

Controllo periodico leggero: se il CSV MBS repost manca ancora (flag
mbs_missing attivo su Supabase), ricontrolla se nel frattempo è comparso
su Drive e, in tal caso, ritriggera A1 Monthly via GitHub API — così
Gianluca vede il foglio aggiornarsi da solo, senza rilanciare nulla a mano.

Gira SOLO dal giorno 2 al giorno 10 del mese, ogni 30 minuti (cron nel
workflow a1_mbs_watcher.yml). Fuori da questa finestra il workflow non
parte proprio: zero run, zero rumore nello storico Actions.

GitHub Actions non supporta run in pausa indefinita in attesa di un
evento esterno (limite 6h sui runner standard) — questo script è la
soluzione: un controllo leggero e periodico, non un'attesa attiva.

Vedi step 20, sezione 3.10.

Variabili d'ambiente richieste:
  GOOGLE_CREDENTIALS  — service account JSON, base64 (stesso pattern di a1_monthly.py)
  SUPABASE_URL / SUPABASE_KEY
  GH_PAT_REPO         — Personal Access Token scope 'repo' (già usato da ig_token_refresh.py
                         per scrivere i GitHub Secrets — stesso PAT, scope sufficiente
                         anche per attivare un workflow_dispatch)
"""

import os
import json
import base64
import re
import requests
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from supabase import create_client

SUPA_URL = os.environ["SUPABASE_URL"]
SUPA_KEY = os.environ["SUPABASE_KEY"]
GH_PAT   = os.environ["GH_PAT_REPO"]

GH_OWNER = "giandcdalcorso11-coder"
GH_REPO  = "GDC-DASHBOARD"

# Stessi valori usati in a1_monthly.py (find_mbs_csv) — tenerli allineati
# se in futuro cambia la cartella o il suffisso del file MBS
MBS_FOLDER_ID   = "1rGgK2yB_MRMi0jvxKWPSIJJJKCtgDnIg"  # Drive "Archivio docs MBS"
MBS_FILE_SUFFIX = "_3909528329355109.csv"

MESE_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"
]


def get_drive_service():
    creds_json = json.loads(base64.b64decode(os.environ["GOOGLE_CREDENTIALS"]))
    creds = Credentials.from_service_account_info(
        creds_json,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)


def parse_mese_label(mese_label):
    """'Giugno 2026' -> (6, 2026). None se il formato non è riconosciuto."""
    try:
        mese_str, anno_str = mese_label.strip().split()
        mese_num = MESE_IT.index(mese_str.lower()) + 1
        return mese_num, int(anno_str)
    except (ValueError, AttributeError):
        return None


def find_mbs_csv(drive_service, mese_num, anno):
    """
    Stessa identica logica di find_mbs_csv() in a1_monthly.py, ma
    parametrizzata su mese/anno invece che sul mese target implicito
    (qui il "mese target" arriva dal flag Supabase, non da oggi-1mese).
    """
    query = f"'{MBS_FOLDER_ID}' in parents and trashed=false and mimeType='text/csv'"
    results = drive_service.files().list(
        q=query, fields="files(id, name, createdTime)"
    ).execute()

    candidates = []
    for f in results.get("files", []):
        name = f["name"]
        if not name.endswith(MBS_FILE_SUFFIX):
            continue
        m = re.match(r"^([A-Za-z]{3})-(\d{2})-(\d{4})_", name)
        if not m:
            continue
        try:
            file_start = datetime.strptime(f"{m.group(1)} {m.group(3)}", "%b %Y").date()
        except ValueError:
            continue
        if file_start.year == anno and file_start.month == mese_num:
            candidates.append(f)

    if not candidates:
        return None
    candidates.sort(key=lambda f: f.get("createdTime", ""), reverse=True)
    return candidates[0]["id"]


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
    print(f"Flag attivo per {mese_label} — controllo 'Archivio docs MBS'...")

    drive = get_drive_service()
    file_id = find_mbs_csv(drive, mese_num, anno)

    if not file_id:
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
