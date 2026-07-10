#!/usr/bin/env python3
"""
GDC IA TEAM — Pipeline Watcher

Scopo (ridefinito allo Step 27 — vedi automatizzazione_step27_GDC_IA_TEAM.docx):
lo scope originale di questo script (auto-rilevamento step 2-5) è in gran
parte obsoleto perché A5.1, A5.2, A6.1, A6.2 e A7 scrivono già da soli
step_attuale a fine sessione. Restano scoperti solo i due passaggi che
dipendono da un evento che accade FUORI da qualunque sessione agente:

  1) Step 3 -> 4 (Media kit -> Approvato)
     Gianluca rivede il PPTX consegnato da A6.1 ed esporta il PDF nella
     stessa cartella Drive (drive_folder_azienda). Nessun agente vede
     quel momento: questo script lo rileva controllando la presenza di
     un PDF nella cartella, per ogni azienda con step_attuale = 3.

  2) Step 6 -> 7 (Bozza Gmail -> Mail inviata)
     Quando Gianluca invia la bozza creata da A7, la bozza smette di
     esistere (drafts.get risponde 404). Per ogni azienda con
     step_attuale = 6, controlliamo se a7_draft_id esiste ancora.
     NOTA: usiamo drafts.get, che richiede solo lo scope gmail.compose
     (già posseduto da A7) — NON serve gmail.readonly, che è uno scope
     "restricted" e richiederebbe un audit CASA a pagamento. Vedi
     discussione Step 27: drafts.get/list/create/update/send accettano
     tutti gmail.compose, quindi nessuna modifica OAuth necessaria.
     Caso limite accettato: se Gianluca cancellasse manualmente una
     bozza senza inviarla, verrebbe interpretata come "inviata". Rischio
     trascurabile per un solo utente che controlla il proprio flusso.

Non retrocede mai step_attuale. Non tocca aziende con dati mancanti o
ambigui (logga e salta). Pensato per girare ogni ora via cron
(pipeline_watcher.yml) — GitHub Actions non supporta un'attesa attiva
oltre le 6h, quindi un controllo periodico leggero è l'architettura
corretta (stesso principio già adottato da a1_mbs_watcher.py).

Variabili d'ambiente richieste:
  GOOGLE_CREDENTIALS    — service account JSON, base64 (stesso pattern degli altri script)
  GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN — stessi di A7
  SUPABASE_URL / SUPABASE_SERVICE_KEY  (service_role: bypassa la RLS, mai l'anon key)
"""

import os
import re
import json
import base64
from datetime import datetime, timezone

import requests
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ── CONFIG ──────────────────────────────────────────────────────────
GOOGLE_CREDENTIALS  = os.environ['GOOGLE_CREDENTIALS']  # base64-encoded service account JSON
GMAIL_CLIENT_ID     = os.environ['GMAIL_CLIENT_ID']
GMAIL_CLIENT_SECRET = os.environ['GMAIL_CLIENT_SECRET']
GMAIL_REFRESH_TOKEN = os.environ['GMAIL_REFRESH_TOKEN']
SUPABASE_URL        = os.environ['SUPABASE_URL']
SUPABASE_KEY        = os.environ['SUPABASE_SERVICE_KEY']

FOLDER_ID_RE = re.compile(r'/folders/([a-zA-Z0-9_-]+)')


# ── DRIVE CLIENT (service account) ──────────────────────────────────
def get_drive_service():
    creds_json = base64.b64decode(GOOGLE_CREDENTIALS).decode('utf-8')
    creds_info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)


# ── GMAIL CLIENT (OAuth refresh token — stesso scope di A7) ─────────
def get_gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=GMAIL_REFRESH_TOKEN,
        client_id=GMAIL_CLIENT_ID,
        client_secret=GMAIL_CLIENT_SECRET,
        token_uri='https://oauth2.googleapis.com/token',
        scopes=['https://www.googleapis.com/auth/gmail.compose']
    )
    creds.refresh(Request())
    return build('gmail', 'v1', credentials=creds)


# ── SUPABASE ─────────────────────────────────────────────────────────
def supabase_headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
    }


def fetch_companies_at_step(step, extra_select=''):
    select = 'id,nome,step_notes' + (f',{extra_select}' if extra_select else '')
    url = (
        f"{SUPABASE_URL}/rest/v1/companies"
        f"?step_attuale=eq.{step}&select={select}"
    )
    r = requests.get(url, headers=supabase_headers(), timeout=10)
    if r.status_code != 200:
        print(f"[WATCHER] Errore lettura companies (step {step}): {r.status_code} {r.text}")
        return []
    return r.json()


def advance_step(company_id, nome, step_num, note_text, current_notes):
    """
    Avanza step_attuale a step_num e marca step_{n}/step_{n}_date/step_notes.
    step_{n}_date scritta sempre a now() (nessun COALESCE — decisione
    Step 26/27, stessa filosofia di a7_gmail_drafter.py).
    """
    now = datetime.now(timezone.utc).isoformat()
    notes = dict(current_notes or {})
    notes[str(step_num)] = note_text

    payload = {
        f'step_{step_num}': True,
        f'step_{step_num}_date': now,
        'step_attuale': step_num,
        'step_notes': notes,
    }
    url = f"{SUPABASE_URL}/rest/v1/companies?id=eq.{company_id}"
    r = requests.patch(url, json=payload, headers=supabase_headers(), timeout=10)
    if r.status_code not in (200, 204):
        print(f"[WATCHER] ⚠ Errore aggiornamento step {step_num} per '{nome}': {r.status_code} {r.text}")
    else:
        print(f"[WATCHER] ✅ '{nome}': step_attuale -> {step_num}")


def extract_folder_id(drive_url):
    """Estrae l'ID cartella da un URL tipo https://drive.google.com/drive/folders/{ID}."""
    if not drive_url:
        return None
    m = FOLDER_ID_RE.search(drive_url)
    return m.group(1) if m else None


# ── CHECK 1 — Step 3 -> 4 (PDF media kit approvato su Drive) ───────
def check_step_3_to_4(drive):
    print("[WATCHER] Controllo step 3 -> 4 (PDF su Drive)...")
    companies = fetch_companies_at_step(3, extra_select='drive_folder_azienda')
    if not companies:
        print("    Nessuna azienda a step 3.")
        return

    for c in companies:
        nome = c.get('nome', '?')
        folder_id = extract_folder_id(c.get('drive_folder_azienda'))
        if not folder_id:
            print(f"    ⚠ '{nome}': drive_folder_azienda mancante o non valido — salto.")
            continue

        try:
            res = drive.files().list(
                q=(
                    f"'{folder_id}' in parents and trashed=false "
                    f"and mimeType='application/pdf'"
                ),
                fields='files(id,name,createdTime)'
            ).execute()
        except HttpError as e:
            print(f"    ⚠ '{nome}': errore Drive ({e}) — salto.")
            continue

        pdfs = res.get('files', [])
        if not pdfs:
            print(f"    '{nome}': nessun PDF ancora — resta a step 3.")
            continue

        pdfs.sort(key=lambda f: f.get('createdTime', ''), reverse=True)
        pdf = pdfs[0]
        print(f"    ✅ '{nome}': PDF trovato ({pdf['name']}) — avanzo a step 4.")
        advance_step(
            c['id'], nome, 4,
            f"PDF approvato rilevato su Drive ({pdf['name']}).",
            c.get('step_notes')
        )


# ── CHECK 2 — Step 6 -> 7 (bozza Gmail inviata) ─────────────────────
def check_step_6_to_7(gmail):
    print("[WATCHER] Controllo step 6 -> 7 (bozza Gmail inviata)...")
    companies = fetch_companies_at_step(6, extra_select='a7_draft_id')
    if not companies:
        print("    Nessuna azienda a step 6.")
        return

    for c in companies:
        nome = c.get('nome', '?')
        draft_id = c.get('a7_draft_id')
        if not draft_id:
            print(f"    ⚠ '{nome}': a7_draft_id mancante — impossibile verificare, salto.")
            continue

        try:
            gmail.users().drafts().get(userId='me', id=draft_id).execute()
            print(f"    '{nome}': bozza ancora presente — non ancora inviata.")
        except HttpError as e:
            if e.resp.status == 404:
                print(f"    ✅ '{nome}': bozza non più trovata (draft_id={draft_id}) — presumo inviata, avanzo a step 7.")
                advance_step(
                    c['id'], nome, 7,
                    f"Bozza Gmail non più presente (draft_id={draft_id}) — presunta inviata.",
                    c.get('step_notes')
                )
            else:
                print(f"    ⚠ '{nome}': errore Gmail imprevisto ({e}) — salto.")


# ── MAIN ─────────────────────────────────────────────────────────────
def main():
    print(f"[WATCHER] Start — {datetime.now(timezone.utc).isoformat()}")

    drive = get_drive_service()
    gmail = get_gmail_service()

    check_step_3_to_4(drive)
    check_step_6_to_7(gmail)

    print(f"[WATCHER] Fine — {datetime.now(timezone.utc).isoformat()}")


if __name__ == '__main__':
    main()
