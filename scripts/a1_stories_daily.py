"""
GDC IA TEAM — Script A1 Stories Daily
Ogni giorno alle 23:50 ora italiana.

Flusso:
1. Instagram Graph API → stories attive in questo momento
2. Aggiunge le stories al file JSON del mese: stories_[mese]_[anno].json
3. Carica il JSON aggiornato su Google Drive (cartella A1.2 → Archivio → [Mese])

Le stories scadono dopo ~24h su Instagram — questo script le cattura
prima che spariscano, costruendo un archivio mensile completo.

Secrets GitHub richiesti:
  IG_ACCESS_TOKEN     — token a lunga durata Instagram Graph API
  IG_USER_ID          — ID numerico account Instagram
  GOOGLE_CREDENTIALS  — JSON service account Google (base64)
  DRIVE_FOLDER_A1     — ID cartella Drive A1.2 root
"""

import os
import json
import base64
import io
import tempfile
import requests
from datetime import datetime, date

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload


# ─── CONFIG ────────────────────────────────────────────────────────────────────

IG_TOKEN     = os.environ["IG_ACCESS_TOKEN"]
IG_USER_ID   = os.environ["IG_USER_ID"]
DRIVE_ROOT   = os.environ["DRIVE_FOLDER_A1"]

today    = date.today()
MESE_IT  = [
    "", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"
][today.month]
ANNO     = today.year
FILENAME = f"stories_{MESE_IT}_{ANNO}.json"

print(f"▶ A1 Stories Daily — {today.strftime('%d/%m/%Y')} — {FILENAME}")


# ─── INSTAGRAM API ──────────────────────────────────────────────────────────────

def ig_get(endpoint, params={}):
    base = f"https://graph.instagram.com/v21.0/{endpoint}"
    params["access_token"] = IG_TOKEN
    r = requests.get(base, params=params)
    r.raise_for_status()
    return r.json()


def fetch_active_stories():
    """
    Recupera tutte le stories attive ora sull'account.
    Le stories sono disponibili solo nelle ~24h dopo la pubblicazione.
    """
    print("  → Fetch stories attive...")
    fields = (
        "id,timestamp,permalink,media_type,"
        "impressions,reach,replies,shares,likes"
    )
    try:
        data = ig_get(f"{IG_USER_ID}/stories", {"fields": fields, "limit": 100})
        stories = data.get("data", [])
    except requests.HTTPError as e:
        if "does not support" in str(e) or "OAuthException" in str(e):
            print(f"    ATTENZIONE: permesso stories non disponibile — {e}")
            return []
        raise

    # Per ogni story, recupera metriche avanzate via insights
    enriched = []
    for s in stories:
        try:
            ins = ig_get(f"{s['id']}/insights", {
                "metric": "impressions,reach,replies,shares,navigation,taps_forward,taps_back,exits,profile_visits,follows"
            })
            metrics = {}
            for m in ins.get("data", []):
                metrics[m["name"]] = m["values"][0]["value"] if m.get("values") else m.get("value", 0)
            s.update(metrics)
        except Exception as ex:
            print(f"    Insights story {s['id']} non disponibili: {ex}")

        # Aggiungi data di capture per log
        s["captured_at"] = datetime.utcnow().isoformat()
        enriched.append(s)

    print(f"    Trovate {len(enriched)} stories attive")
    return enriched


# ─── GOOGLE DRIVE ───────────────────────────────────────────────────────────────

def get_drive_service():
    creds_b64  = os.environ["GOOGLE_CREDENTIALS"]
    creds_json = json.loads(base64.b64decode(creds_b64))
    scopes     = ["https://www.googleapis.com/auth/drive"]
    creds      = Credentials.from_service_account_info(creds_json, scopes=scopes)
    return build("drive", "v3", credentials=creds)


def find_or_create_folder(service, name, parent_id):
    """Trova una cartella per nome in parent, o la crea se non esiste."""
    query = (
        f"name='{name}' and '{parent_id}' in parents "
        f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    # Crea la cartella
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id]
    }
    folder = service.files().create(body=meta, fields="id").execute()
    print(f"    Cartella '{name}' creata su Drive")
    return folder["id"]


def find_file(service, name, folder_id):
    query = f"name='{name}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None


def download_json(service, file_id):
    """Scarica il JSON esistente e ritorna lista Python."""
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return json.loads(fh.read())


def upload_json(service, data, filename, folder_id, existing_id=None):
    """Carica (o aggiorna) il file JSON su Drive."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_path = f.name

    media = MediaFileUpload(tmp_path, mimetype="application/json")

    if existing_id:
        service.files().update(fileId=existing_id, media_body=media).execute()
        print(f"    JSON aggiornato: {filename} ({len(data)} stories totali)")
    else:
        meta = {"name": filename, "parents": [folder_id]}
        service.files().create(body=meta, media_body=media, fields="id").execute()
        print(f"    JSON creato: {filename} ({len(data)} stories)")

    os.unlink(tmp_path)


# ─── DEDUPLICAZIONE ─────────────────────────────────────────────────────────────

def merge_stories(existing, new_stories):
    """
    Unisce le nuove stories con quelle esistenti.
    Deduplica per ID — aggiorna le metriche se la story era già presente
    (le metriche cambiano durante le 24h di vita della story).
    """
    existing_map = {s["id"]: s for s in existing}

    updated = 0
    added   = 0
    for s in new_stories:
        sid = s["id"]
        if sid in existing_map:
            # Aggiorna metriche (potrebbero essere più alte)
            existing_map[sid].update(s)
            updated += 1
        else:
            existing_map[sid] = s
            added += 1

    result = list(existing_map.values())
    # Ordina per timestamp decrescente
    result.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    print(f"    Merge: {added} nuove, {updated} aggiornate, {len(result)} totali")
    return result


# ─── MAIN ─────────────────────────────────────────────────────────────────────────

def main():
    # 1. Fetch stories attive ora
    new_stories = fetch_active_stories()

    if not new_stories:
        print("  Nessuna story attiva — nulla da salvare")
        return

    # 2. Setup Drive
    service = get_drive_service()

    # 3. Trova/crea struttura cartelle: A1.2 → Archivio → [Mese Anno]
    archivio_id = find_or_create_folder(service, "Archivio", DRIVE_ROOT)
    mese_folder_name = f"{MESE_IT.capitalize()} {ANNO}"
    mese_folder_id   = find_or_create_folder(service, mese_folder_name, archivio_id)

    # 4. Scarica JSON esistente (se c'è) e unisci
    existing_id = find_file(service, FILENAME, mese_folder_id)
    if existing_id:
        print(f"  → File esistente trovato, carico...")
        existing_stories = download_json(service, existing_id)
        print(f"    Già archiviate: {len(existing_stories)} stories")
    else:
        existing_stories = []

    merged = merge_stories(existing_stories, new_stories)

    # 5. Carica JSON aggiornato su Drive
    upload_json(service, merged, FILENAME, mese_folder_id, existing_id)

    print(f"\n✅ Stories Daily completato — {today.strftime('%d/%m/%Y')}")
    print(f"   Stories nel file: {len(merged)}")


if __name__ == "__main__":
    main()
