"""
GDC IA TEAM — Script A1 Stories Daily
Ogni giorno alle 23:50 ora italiana.

Flusso:
1. Instagram Graph API → stories attive in questo momento
2. Scrive le stories su Google Sheet A1, tab "Stories_[Mese]_[Anno]"
   (upsert per ID — aggiorna metriche se la story è già presente)

Le stories scadono dopo ~24h su Instagram — questo script le cattura
prima che spariscano, costruendo un archivio mensile completo.

Nota: salvataggio su Google Sheets invece di Drive JSON perché
i service account non hanno storage quota su Drive personale.

Secrets GitHub richiesti:
  IG_ACCESS_TOKEN     — token a lunga durata Instagram Graph API
  IG_USER_ID          — ID numerico account Instagram
  GOOGLE_CREDENTIALS  — JSON service account Google (base64)
"""

import os
import json
import base64
import requests
from datetime import datetime, date

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


# ─── CONFIG ────────────────────────────────────────────────────────────────────

IG_TOKEN   = os.environ["IG_ACCESS_TOKEN"]
IG_USER_ID = os.environ["IG_USER_ID"]

SHEET_ID = "1puwwEmieMPGIaY_xgBPO682HCZKDcIlDvJOWdu2lz30"

today   = date.today()
MESI_IT = [
    "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
]
MESE_IT  = MESI_IT[today.month]
ANNO     = today.year
TAB_NAME = f"Stories_{MESE_IT}_{ANNO}"

COLUMNS = [
    "story_id", "timestamp", "media_type", "permalink",
    "captured_at",
    "views", "reach", "replies",
    "navigation",
    "profile_visits", "follows", "shares"
]

# Metriche sicure per stories (period=lifetime obbligatorio)
# Suddivise in core (sempre disponibili) e extra (tentativo separato)
# Nota (step 20, 3.4): impressions -> views; taps_forward/taps_back/exits
# consolidate nell'aggregato unico navigation (non piu' scomponibile via API)
METRICS_CORE  = "views,reach,replies,navigation"
METRICS_EXTRA = ["profile_visits", "follows", "shares"]

print(f"▶ A1 Stories Daily — {today.strftime('%d/%m/%Y')} — tab: {TAB_NAME}")


# ─── INSTAGRAM API ──────────────────────────────────────────────────────────────

def ig_get(endpoint, params={}):
    base = f"https://graph.facebook.com/v21.0/{endpoint}"
    params["access_token"] = IG_TOKEN
    r = requests.get(base, params=params)
    r.raise_for_status()
    return r.json()


def fetch_story_insights(story_id):
    """
    Recupera metriche per una singola story.
    Strategia a due livelli:
    1. Chiama le metriche core con period=lifetime (obbligatorio per stories)
    2. Tenta le metriche extra una per una — le salta se non disponibili
    """
    metrics = {}

    # Livello 1 — metriche core (sempre disponibili)
    try:
        ins = ig_get(f"{story_id}/insights", {
            "metric": METRICS_CORE,
            "period": "lifetime"
        })
        for m in ins.get("data", []):
            val = m["values"][0]["value"] if m.get("values") else m.get("value", 0)
            metrics[m["name"]] = val
    except Exception as e:
        print(f"      Core insights non disponibili per {story_id}: {e}")

    # Livello 2 — metriche extra (tentativo individuale)
    for metric in METRICS_EXTRA:
        try:
            ins = ig_get(f"{story_id}/insights", {
                "metric": metric,
                "period": "lifetime"
            })
            for m in ins.get("data", []):
                val = m["values"][0]["value"] if m.get("values") else m.get("value", 0)
                metrics[m["name"]] = val
        except Exception:
            pass  # metrica non disponibile per questa story — skip silenzioso

    return metrics


def fetch_active_stories():
    """Recupera tutte le stories attive + metriche via insights."""
    print("  → Fetch stories attive...")
    fields = "id,timestamp,permalink,media_type"
    try:
        data = ig_get(f"{IG_USER_ID}/stories", {"fields": fields, "limit": 100})
        stories = data.get("data", [])
    except requests.HTTPError as e:
        print(f"    ATTENZIONE: permesso stories non disponibile — {e}")
        return []

    if not stories:
        print("    Nessuna story attiva al momento")
        return []

    enriched = []
    for s in stories:
        print(f"    Story {s['id']} ({s.get('media_type','')}) — fetch insights...")
        ins = fetch_story_insights(s["id"])
        s.update(ins)
        s["captured_at"] = datetime.utcnow().isoformat()
        enriched.append(s)
        print(f"      views={ins.get('views','?')}  reach={ins.get('reach','?')}  replies={ins.get('replies','?')}")

    print(f"    Trovate {len(enriched)} stories attive")
    return enriched


# ─── GOOGLE SHEETS ──────────────────────────────────────────────────────────────

def get_sheets_service():
    creds_b64  = os.environ["GOOGLE_CREDENTIALS"]
    creds_json = json.loads(base64.b64decode(creds_b64))
    scopes     = ["https://www.googleapis.com/auth/spreadsheets"]
    creds      = Credentials.from_service_account_info(creds_json, scopes=scopes)
    return build("sheets", "v4", credentials=creds)


def ensure_tab(service, tab_name):
    """Crea il tab se non esiste."""
    meta = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    existing = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if tab_name in existing:
        return False
    body = {"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
    service.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body=body).execute()
    print(f"    Tab '{tab_name}' creato")
    return True


def write_header(service, tab_name):
    service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{tab_name}'!A1",
        valueInputOption="RAW",
        body={"values": [COLUMNS]}
    ).execute()


def read_existing_ids(service, tab_name):
    """Legge gli story_id già presenti (colonna A dalla riga 2)."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f"'{tab_name}'!A2:A"
        ).execute()
        rows = result.get("values", [])
        return {row[0] for row in rows if row}
    except Exception:
        return set()


def story_to_row(s):
    """Converte un dict story nella lista di valori per il foglio."""
    return [str(s.get(col, "")) for col in COLUMNS]


def upsert_stories(service, tab_name, stories):
    """
    Upsert stories:
    - Nuove (ID non presente) → append in fondo
    - Già presenti → aggiorna le metriche sulla riga esistente
    """
    # Leggi tutte le righe esistenti per trovare posizione per ID
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f"'{tab_name}'!A2:A"
        ).execute()
        existing_rows = result.get("values", [])
    except Exception:
        existing_rows = []

    id_to_row = {}
    for i, row in enumerate(existing_rows, start=2):
        if row:
            id_to_row[row[0]] = i

    new_rows    = []
    updated     = 0
    skipped     = 0

    for s in stories:
        sid = s.get("id") or s.get("story_id", "")
        if not sid:
            continue
        s_mapped = {**s, "story_id": sid}
        row_data = story_to_row(s_mapped)

        if sid in id_to_row:
            # Aggiorna riga esistente con metriche aggiornate
            row_num = id_to_row[sid]
            service.spreadsheets().values().update(
                spreadsheetId=SHEET_ID,
                range=f"'{tab_name}'!A{row_num}",
                valueInputOption="RAW",
                body={"values": [row_data]}
            ).execute()
            updated += 1
        else:
            new_rows.append(row_data)

    if new_rows:
        service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=f"'{tab_name}'!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": new_rows}
        ).execute()

    print(f"    Nuove stories aggiunte: {len(new_rows)} | Aggiornate: {updated}")
    return len(new_rows), updated


# ─── MAIN ─────────────────────────────────────────────────────────────────────────

def main():
    # 1. Fetch stories attive
    new_stories = fetch_active_stories()

    if not new_stories:
        print("  Nessuna story attiva — nulla da salvare")
        return

    # 2. Setup Sheets
    service = get_sheets_service()

    # 3. Assicura che il tab del mese esista
    is_new = ensure_tab(service, TAB_NAME)
    if is_new:
        write_header(service, TAB_NAME)

    # Assicura header se tab esisteva ma era vuoto
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f"'{TAB_NAME}'!A1:A1"
        ).execute()
        if not result.get("values"):
            write_header(service, TAB_NAME)
    except Exception:
        pass

    # 4. Upsert stories (append nuove, aggiorna metriche esistenti)
    added, updated = upsert_stories(service, TAB_NAME, new_stories)

    print(f"\n✅ Stories Daily completato — {today.strftime('%d/%m/%Y')}")
    print(f"   Nuove stories aggiunte: {added}")
    print(f"   Stories aggiornate: {updated}")
    print(f"   Sheet: {SHEET_ID} — tab: {TAB_NAME}")


if __name__ == "__main__":
    main()
