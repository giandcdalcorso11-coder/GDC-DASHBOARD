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

# Sheet A1 — ID fisso dal progetto (non richiede secret separato)
SHEET_ID = "1puwwEmieMPGIaY_xgBPO682HCZKDcIlDvJOWdu2lz30"

today   = date.today()
MESI_IT = [
    "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
]
MESE_IT  = MESI_IT[today.month]
ANNO     = today.year
TAB_NAME = f"Stories_{MESE_IT}_{ANNO}"   # es. "Stories_Giugno_2026"

COLUMNS = [
    "story_id", "timestamp", "media_type", "permalink",
    "captured_at",
    "impressions", "reach", "replies",
    "taps_forward", "taps_back", "exits",
    "profile_visits", "follows"
]

print(f"▶ A1 Stories Daily — {today.strftime('%d/%m/%Y')} — tab: {TAB_NAME}")


# ─── INSTAGRAM API ──────────────────────────────────────────────────────────────

def ig_get(endpoint, params={}):
    base = f"https://graph.facebook.com/v21.0/{endpoint}"
    params["access_token"] = IG_TOKEN
    r = requests.get(base, params=params)
    r.raise_for_status()
    return r.json()


def fetch_active_stories():
    """Recupera tutte le stories attive + metriche via insights."""
    print("  → Fetch stories attive...")
    fields = "id,timestamp,permalink,media_type"
    try:
        data = ig_get(f"{IG_USER_ID}/stories", {"fields": fields, "limit": 100})
        stories = data.get("data", [])
    except requests.HTTPError as e:
        if "does not support" in str(e) or "OAuthException" in str(e):
            print(f"    ATTENZIONE: permesso stories non disponibile — {e}")
            return []
        raise

    # Metriche valide per stories: NO shares/likes/navigation (non supportati)
    INSIGHTS_METRICS = "impressions,reach,replies,taps_forward,taps_back,exits,profile_visits,follows"

    enriched = []
    for s in stories:
        try:
            ins = ig_get(f"{s['id']}/insights", {"metric": INSIGHTS_METRICS})
            for m in ins.get("data", []):
                val = m["values"][0]["value"] if m.get("values") else m.get("value", 0)
                s[m["name"]] = val
        except Exception as ex:
            print(f"    Insights story {s['id']} non disponibili: {ex}")

        s["captured_at"] = datetime.utcnow().isoformat()
        enriched.append(s)

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
    """Crea il tab se non esiste. Ritorna True se appena creato."""
    meta = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    existing = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if tab_name in existing:
        return False
    # Crea tab
    body = {"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
    service.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body=body).execute()
    print(f"    Tab '{tab_name}' creato")
    return True


def write_header(service, tab_name):
    """Scrive la riga di intestazione."""
    service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"'{tab_name}'!A1",
        valueInputOption="RAW",
        body={"values": [COLUMNS]}
    ).execute()


def read_existing_ids(service, tab_name):
    """Legge gli story_id già presenti nella colonna A (dalla riga 2 in poi)."""
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


def append_stories(service, tab_name, stories):
    """Aggiunge le nuove stories in fondo al tab (upsert per ID)."""
    existing_ids = read_existing_ids(service, tab_name)

    new_rows = []
    skipped  = 0
    for s in stories:
        sid = s.get("id") or s.get("story_id", "")
        if not sid:
            continue
        if sid in existing_ids:
            skipped += 1
            continue
        # Mappa "id" → "story_id" per il foglio
        s_mapped = {**s, "story_id": sid}
        new_rows.append(story_to_row(s_mapped))

    if new_rows:
        service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=f"'{tab_name}'!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": new_rows}
        ).execute()
        print(f"    Scritte {len(new_rows)} nuove stories ({skipped} già presenti)")
    else:
        print(f"    Nessuna nuova story da aggiungere ({skipped} già presenti)")

    return len(new_rows)


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

    # 4. Upsert stories (append solo quelle nuove per ID)
    added = append_stories(service, TAB_NAME, new_stories)

    print(f"\n✅ Stories Daily completato — {today.strftime('%d/%m/%Y')}")
    print(f"   Nuove stories aggiunte: {added}")
    print(f"   Sheet: {SHEET_ID} — tab: {TAB_NAME}")


if __name__ == "__main__":
    main()
