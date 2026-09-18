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
     Quando Gianluca invia la bozza creata da A7, la bozza sparisce dalla
     cartella Bozze. Per ogni azienda con step_attuale = 6, controlliamo
     se il suo a7_draft_id compare ancora tra le bozze attualmente presenti
     (drafts().list(), non drafts().get(id) — vedi nota Step 34 sotto).
     NOTA: usiamo solo drafts.list/get, che richiedono lo scope gmail.compose
     (già posseduto da A7) — NON serve gmail.readonly, che è uno scope
     "restricted" e richiederebbe un audit CASA a pagamento.
     Caso limite accettato: se Gianluca cancellasse manualmente una
     bozza senza inviarla, verrebbe interpretata come "inviata". Rischio
     trascurabile per un solo utente che controlla il proprio flusso.

     CORREZIONE Step 34 (verificata su 3 casi reali: Anthros, Diablo
     Chairs, Sparco — inviate il 17/09 ma mai avanzate a step 7):
     l'assunzione originale "drafts.get(id) risponde 404 dopo l'invio" è
     risultata falsa in pratica — drafts.get(id) può continuare a
     risolvere l'id anche a bozza inviata, restituendo il messaggio con
     label SENT invece di 404. Sostituito con drafts().list(): riflette
     sempre lo stato reale della cartella Bozze ed è la fonte di verità
     usata anche per la conferma manuale in chat. Gestisce anche il caso
     multi-bozza (a7_draft_id come lista comma-separata, introdotto da
     a7_gmail_drafter.py v4 il 26/07 — pipeline_watcher.py non era mai
     stato aggiornato di conseguenza da quando è stato scritto, 10/07).

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
def list_current_draft_ids(gmail):
    """
    Elenco di TUTTI i draft_id attualmente presenti nella cartella Bozze.
    Sostituisce il vecchio approccio drafts().get(id) + 404: verificato
    (Step 34) che una volta inviata la bozza, drafts().get(id) NON risponde
    sempre 404 come da assunzione originale — a volte continua a risolvere
    l'id restituendo il messaggio ormai inviato (label SENT al posto di
    DRAFT), quindi il 404 da solo non è un segnale affidabile. drafts().list()
    invece riflette sempre lo stato reale della cartella Bozze: se un id non
    ci compare più, la bozza è stata inviata (o cancellata a mano — stesso
    caso limite accettato di prima, rischio trascurabile per un solo utente).
    """
    ids = set()
    page_token = None
    while True:
        resp = gmail.users().drafts().list(
            userId='me', maxResults=100, pageToken=page_token
        ).execute()
        ids.update(d['id'] for d in resp.get('drafts', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return ids


def check_step_6_to_7(gmail):
    print("[WATCHER] Controllo step 6 -> 7 (bozza Gmail inviata)...")
    companies = fetch_companies_at_step(6, extra_select='a7_draft_id')
    if not companies:
        print("    Nessuna azienda a step 6.")
        return

    current_draft_ids = list_current_draft_ids(gmail)

    for c in companies:
        nome = c.get('nome', '?')
        draft_id_raw = c.get('a7_draft_id')
        if not draft_id_raw:
            print(f"    ⚠ '{nome}': a7_draft_id mancante — impossibile verificare, salto.")
            continue

        # a7_gmail_drafter.py (v4, Luglio 2026) può creare più bozze per la
        # stessa azienda (multi-destinatario) e salva a7_draft_id come lista
        # comma-separata. Avanza solo quando NESSUNA delle bozze è più
        # presente — se anche una sola è ancora in sospeso, l'azienda resta
        # a step 6.
        ids = [d.strip() for d in draft_id_raw.split(',') if d.strip()]
        still_pending = [d for d in ids if d in current_draft_ids]
        if still_pending:
            print(f"    '{nome}': {len(still_pending)}/{len(ids)} bozza/e ancora presente/i — non ancora inviata/e.")
            continue

        print(f"    ✅ '{nome}': nessuna bozza più presente ({draft_id_raw}) — presumo inviata/e, avanzo a step 7.")
        advance_step(
            c['id'], nome, 7,
            f"Bozza/e Gmail non più presente/i ({draft_id_raw}) — presunta/e inviata/e.",
            c.get('step_notes')
        )


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
