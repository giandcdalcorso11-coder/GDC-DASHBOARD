#!/usr/bin/env python3
"""
GDC IA TEAM — Agente 7 — Gmail Drafter
Trigger: workflow_dispatch da home webapp con parametro company_name.

Flusso:
  1. Riceve company_name come parametro
  2. Cerca TXT (mail_*.txt) e PDF nella cartella Drive A6/Aziende/[NOME AZIENDA]/
  3. Se PDF assente: stop con errore
  4. Se entrambi presenti: crea bozza Gmail con PDF allegato
  5. Aggiorna Supabase companies (a7_status, a7_processed_at, a7_draft_id, a7_processed_file_id)
  6. Aggiorna Supabase companies — pipeline step 6 "Bozza Gmail" (step_6, step_6_date, step_notes,
     step_attuale se non gia' avanzato oltre da Gianluca) — v2, Luglio 2026
  7. Aggiorna Supabase agent_states (stato a7)

Formato TXT (mail_[AZIENDA]_YYYY-MM-DD.txt):
  TO: email@azienda.com
  SUBJECT: Oggetto della mail
  ATTACHMENT: media_kit_[AZIENDA].pdf
  LANGUAGE: IT

  Corpo della mail qui.
  Tutto il testo.
  Firma inclusa.

Nota sulla ricerca azienda su Supabase (v3, Luglio 2026):
  La corrispondenza col nome e' parziale (ilike '%company_name%'), non piu'
  esatta — cosi' digitare "Barbuscia" trova comunque "Barbuscia S.p.A.".
  Se il nome passato corrisponde a PIU' di un'azienda, lo script non
  aggiorna nulla su Supabase (per evitare di scrivere sull'azienda
  sbagliata) e stampa un avviso con i nomi in conflitto: in quel caso
  rilanciare specificando il nome per esteso.
"""

import os
import sys
import base64
import json
import io
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


# ── CONFIG ──────────────────────────────────────────────────────────
DRIVE_FOLDER_A6_AZIENDE = os.environ['DRIVE_FOLDER_A6_AZIENDE']  # 1BdHr1tG_EjTzRzaVgk368TtL1DaJzFP_
GMAIL_CLIENT_ID         = os.environ['GMAIL_CLIENT_ID']
GMAIL_CLIENT_SECRET     = os.environ['GMAIL_CLIENT_SECRET']
GMAIL_REFRESH_TOKEN     = os.environ['GMAIL_REFRESH_TOKEN']
GOOGLE_CREDENTIALS      = os.environ['GOOGLE_CREDENTIALS']  # base64-encoded service account JSON
SUPABASE_URL            = os.environ['SUPABASE_URL']        # https://pnzabwfsgkvejnrtrjcp.supabase.co
SUPABASE_KEY            = os.environ['SUPABASE_SERVICE_KEY']  # service_role: bypassa la RLS, mai l'anon key
COMPANY_NAME            = os.environ['COMPANY_NAME']        # passato via workflow_dispatch
GMAIL_FROM              = 'giandcdalcorso11@gmail.com'


# ── DRIVE CLIENT (service account) ──────────────────────────────────
def get_drive_service():
    from google.oauth2 import service_account

    # GOOGLE_CREDENTIALS è base64-encoded nel GitHub Secret
    creds_json = base64.b64decode(GOOGLE_CREDENTIALS).decode('utf-8')
    creds_info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=['https://www.googleapis.com/auth/drive']
    )
    return build('drive', 'v3', credentials=creds)


# ── GMAIL CLIENT (OAuth refresh token) ──────────────────────────────
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


# ── DRIVE HELPERS ────────────────────────────────────────────────────
def find_company_folder(drive, aziende_folder_id, company_name):
    """Trova la sottocartella [NOME AZIENDA] dentro A6/Aziende/."""
    res = drive.files().list(
        q=(
            f"name='{company_name}' "
            f"and mimeType='application/vnd.google-apps.folder' "
            f"and '{aziende_folder_id}' in parents "
            f"and trashed=false"
        ),
        fields='files(id,name)'
    ).execute()
    files = res.get('files', [])
    if not files:
        return None
    return files[0]['id']


def list_files_in_folder(drive, folder_id):
    """Lista tutti i file in una cartella Drive."""
    res = drive.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields='files(id,name,mimeType,createdTime)'
    ).execute()
    return res.get('files', [])


def find_txt_in_files(files):
    """Trova il file mail_*.txt più recente tra i file listati."""
    txts = [f for f in files if f['name'].startswith('mail_') and f['name'].endswith('.txt')]
    if not txts:
        return None
    # Ordina per data creazione decrescente, prende il più recente
    txts.sort(key=lambda f: f.get('createdTime', ''), reverse=True)
    return txts[0]


def find_pdf_in_files(files):
    """Trova il file PDF tra i file listati."""
    pdfs = [f for f in files if f['mimeType'] == 'application/pdf']
    if not pdfs:
        return None
    pdfs.sort(key=lambda f: f.get('createdTime', ''), reverse=True)
    return pdfs[0]


def download_file_text(drive, file_id):
    """Scarica il contenuto testuale di un file Drive."""
    request = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue().decode('utf-8')


def download_file_bytes(drive, file_id):
    """Scarica i byte di un file Drive (per PDF allegato)."""
    request = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


# ── TXT PARSER ───────────────────────────────────────────────────────
def parse_mail_txt(content):
    """
    Parsa il file TXT con formato:
      TO: email
      SUBJECT: oggetto
      ATTACHMENT: filename.pdf
      LANGUAGE: IT/EN
      [riga vuota]
      corpo mail...
    """
    lines = content.strip().split('\n')
    headers = {}
    body_lines = []
    in_body = False

    for line in lines:
        if in_body:
            body_lines.append(line)
            continue
        if line.strip() == '':
            in_body = True
            continue
        if ':' in line:
            key, _, value = line.partition(':')
            headers[key.strip().upper()] = value.strip()

    return headers, '\n'.join(body_lines).strip()


# ── GMAIL DRAFT ──────────────────────────────────────────────────────
def create_gmail_draft(gmail, to_addr, subject, body_text, pdf_bytes, pdf_filename):
    """Crea una bozza Gmail con allegato PDF."""
    msg = MIMEMultipart()
    msg['to'] = to_addr
    msg['from'] = GMAIL_FROM
    msg['subject'] = subject
    msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

    attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
    attachment.add_header(
        'Content-Disposition', 'attachment',
        filename=pdf_filename
    )
    msg.attach(attachment)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = gmail.users().drafts().create(
        userId='me',
        body={'message': {'raw': raw}}
    ).execute()
    return draft['id']


# ── SUPABASE ─────────────────────────────────────────────────────────
def supabase_headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
    }


def update_agent_state(stato):
    """Aggiorna agent_states per a7."""
    payload = {
        'stato': stato,
        'updated_at': datetime.now(timezone.utc).isoformat()
    }
    url = f"{SUPABASE_URL}/rest/v1/agent_states?agent_id=eq.a7"
    r = requests.patch(url, json=payload, headers=supabase_headers(), timeout=10)
    if r.status_code not in (200, 204):
        print(f"[A7] Warning agent_states: {r.status_code} {r.text}")


def find_company_row(company_name, select='id'):
    """
    Cerca l'azienda per nome, tollerante a corrispondenze parziali
    (es. 'Barbuscia' trova 'Barbuscia S.p.A.').

    Ritorna: (row, None) se trovata UNA sola corrispondenza,
             (None, 'not_found') se nessuna corrispondenza,
             (None, 'ambiguous') se piu' di una corrispondenza — in questo
             caso NON si procede mai con un aggiornamento alla cieca, per
             evitare di scrivere sull'azienda sbagliata.
    """
    url = (
        f"{SUPABASE_URL}/rest/v1/companies"
        f"?nome=ilike.*{requests.utils.quote(company_name)}*"
        f"&select={select}"
    )
    r = requests.get(url, headers=supabase_headers(), timeout=10)
    if r.status_code != 200:
        print(f"[A7] Warning lettura companies: {r.status_code} {r.text}")
        return None, 'error'
    rows = r.json()
    if not rows:
        return None, 'not_found'
    if len(rows) > 1:
        nomi = [row.get('nome', '?') for row in rows]
        print(f"[A7] ATTENZIONE: '{company_name}' corrisponde a piu' aziende {nomi} — nessun aggiornamento Supabase per evitare ambiguita'. Usa il nome esatto.")
        return None, 'ambiguous'
    return rows[0], None


def update_company_a7(company_name, status, draft_id=None, file_id=None):
    """Aggiorna le colonne a7_* nella tabella companies per questa azienda."""
    row, err = find_company_row(company_name, select='id,nome')
    if err:
        print(f"[A7] Nessun aggiornamento a7_status per '{company_name}' ({err})")
        return

    payload = {
        'a7_status': status,
        'a7_processed_at': datetime.now(timezone.utc).isoformat(),
    }
    if draft_id:
        payload['a7_draft_id'] = draft_id
    if file_id:
        payload['a7_processed_file_id'] = file_id

    url = f"{SUPABASE_URL}/rest/v1/companies?id=eq.{row['id']}"
    r = requests.patch(url, json=payload, headers=supabase_headers(), timeout=10)
    if r.status_code not in (200, 204):
        print(f"[A7] Warning companies: {r.status_code} {r.text}")
    else:
        print(f"[A7] Supabase companies aggiornato ({row['nome']}): a7_status={status}")


# ── PIPELINE STEP 6 — Bozza Gmail ───────────────────────────────────
# NOTA: la REST API di PostgREST non supporta il merge jsonb '||' in un
# singolo PATCH come fa il connector SQL usato dagli agenti Claude. Qui
# serve prima una GET per leggere lo stato attuale, poi calcolare il
# merge di step_notes in Python, poi il PATCH.
# step_6_date viene sempre scritta a now() (nessun COALESCE): riflette
# l'ultimo aggiornamento, non il primo — allineato alla stessa filosofia
# già adottata dalla webapp e dagli altri agenti (decisione Step 26/27).

def update_pipeline_step_6(company_name, draft_id):
    """
    Avanza la pipeline a step 6 (Bozza Gmail) dopo la creazione della bozza.
    Non retrocede mai: se step_attuale e' gia' >= 6 (Gianluca ha avanzato
    oltre a mano), lascia step_attuale invariato ma aggiorna comunque
    step_6 / step_6_date / step_notes per coerenza della timeline.
    """
    row, err = find_company_row(company_name, select='id,nome,step_attuale,step_6_date,step_notes')
    if err:
        print(f"[A7] Impossibile aggiornare step 6 per '{company_name}' ({err})")
        return

    current_step = row.get('step_attuale') or 0
    step_6_date = datetime.now(timezone.utc).isoformat()
    notes = row.get('step_notes') or {}
    notes['6'] = f"Bozza Gmail creata (draft_id={draft_id})."

    payload = {
        'step_1': True, 'step_2': True, 'step_3': True,
        'step_4': True, 'step_5': True, 'step_6': True,
        'step_6_date': step_6_date,
        'step_notes': notes,
    }
    if current_step < 6:
        payload['step_attuale'] = 6

    url = f"{SUPABASE_URL}/rest/v1/companies?id=eq.{row['id']}"
    r = requests.patch(url, json=payload, headers=supabase_headers(), timeout=10)
    if r.status_code not in (200, 204):
        print(f"[A7] Warning aggiornamento step 6: {r.status_code} {r.text}")
    else:
        print(f"[A7] Step pipeline aggiornato: step_6=true, step_attuale={payload.get('step_attuale', current_step)}")


# ── MAIN ─────────────────────────────────────────────────────────────
def main():
    print(f"[A7] Start — {datetime.now(timezone.utc).isoformat()}")
    print(f"[A7] Azienda: {COMPANY_NAME}")

    update_agent_state('working')

    try:
        drive = get_drive_service()
        gmail = get_gmail_service()

        # 1. Trova sottocartella azienda in A6/Aziende/
        company_folder_id = find_company_folder(drive, DRIVE_FOLDER_A6_AZIENDE, COMPANY_NAME)
        if not company_folder_id:
            msg = f"Cartella '{COMPANY_NAME}' non trovata in Drive A6/Aziende/"
            print(f"[A7] ERRORE: {msg}")
            update_agent_state('idle')
            update_company_a7(COMPANY_NAME, 'error')
            sys.exit(1)

        print(f"[A7] Cartella azienda trovata: {company_folder_id}")

        # 2. Lista file nella cartella
        files = list_files_in_folder(drive, company_folder_id)
        print(f"[A7] File trovati nella cartella: {[f['name'] for f in files]}")

        # 3. Trova TXT
        txt_file = find_txt_in_files(files)
        if not txt_file:
            print(f"[A7] ERRORE: nessun file mail_*.txt trovato in A6/Aziende/{COMPANY_NAME}/")
            update_agent_state('idle')
            update_company_a7(COMPANY_NAME, 'error')
            sys.exit(1)

        print(f"[A7] TXT trovato: {txt_file['name']}")

        # 4. Trova PDF — se assente: stop
        pdf_file = find_pdf_in_files(files)
        if not pdf_file:
            print(f"[A7] ERRORE: nessun PDF trovato in A6/Aziende/{COMPANY_NAME}/")
            print(f"[A7] Caricare il PDF prima di lanciare A7.")
            update_agent_state('idle')
            update_company_a7(COMPANY_NAME, 'error')
            sys.exit(1)

        print(f"[A7] PDF trovato: {pdf_file['name']}")

        # 5. Scarica e parsa il TXT
        txt_content = download_file_text(drive, txt_file['id'])
        headers, body = parse_mail_txt(txt_content)

        to_addr = headers.get('TO', '').strip()
        subject  = headers.get('SUBJECT', '(nessun oggetto)').strip()

        if not to_addr:
            print(f"[A7] ERRORE: campo TO mancante nel TXT")
            update_agent_state('idle')
            update_company_a7(COMPANY_NAME, 'error')
            sys.exit(1)

        print(f"[A7] TO: {to_addr}")
        print(f"[A7] SUBJECT: {subject}")

        # 6. Scarica PDF
        pdf_bytes = download_file_bytes(drive, pdf_file['id'])
        print(f"[A7] PDF scaricato: {len(pdf_bytes) // 1024} KB")

        # 7. Crea bozza Gmail
        draft_id = create_gmail_draft(
            gmail,
            to_addr=to_addr,
            subject=subject,
            body_text=body,
            pdf_bytes=pdf_bytes,
            pdf_filename=pdf_file['name']
        )
        print(f"[A7] Bozza Gmail creata: {draft_id}")

        # 8. Aggiorna Supabase
        update_company_a7(
            COMPANY_NAME,
            status='drafted',
            draft_id=draft_id,
            file_id=txt_file['id']
        )
        update_pipeline_step_6(COMPANY_NAME, draft_id)
        update_agent_state('done')

        print(f"[A7] Fine — bozza creata con successo per {COMPANY_NAME}")

    except Exception as e:
        print(f"[A7] ERRORE imprevisto: {e}")
        import traceback
        traceback.print_exc()
        update_agent_state('idle')
        update_company_a7(COMPANY_NAME, 'error')
        sys.exit(1)


if __name__ == '__main__':
    main()
