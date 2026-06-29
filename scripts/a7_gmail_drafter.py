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
  6. Aggiorna Supabase agent_states (stato a7)

Formato TXT (mail_[AZIENDA]_YYYY-MM-DD.txt):
  TO: email@azienda.com
  SUBJECT: Oggetto della mail
  ATTACHMENT: media_kit_[AZIENDA].pdf
  LANGUAGE: IT

  Corpo della mail qui.
  Tutto il testo.
  Firma inclusa.
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
SUPABASE_KEY            = os.environ['SUPABASE_KEY']
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


def update_company_a7(company_name, status, draft_id=None, file_id=None):
    """Aggiorna le colonne a7_* nella tabella companies per questa azienda."""
    payload = {
        'a7_status': status,
        'a7_processed_at': datetime.now(timezone.utc).isoformat(),
    }
    if draft_id:
        payload['a7_draft_id'] = draft_id
    if file_id:
        payload['a7_processed_file_id'] = file_id

    # Usa nome azienda come chiave (case-insensitive con ilike)
    url = f"{SUPABASE_URL}/rest/v1/companies?nome=ilike.{requests.utils.quote(company_name)}"
    r = requests.patch(url, json=payload, headers=supabase_headers(), timeout=10)
    if r.status_code not in (200, 204):
        print(f"[A7] Warning companies: {r.status_code} {r.text}")
    else:
        print(f"[A7] Supabase companies aggiornato: a7_status={status}")


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
