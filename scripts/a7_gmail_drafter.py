#!/usr/bin/env python3
"""
GDC IA TEAM — Agente 7 — Gmail Drafter
GitHub Actions script: polling Drive A6 ogni 15 min.

Flusso:
  1. Lista file mail_*.txt in Drive A6 non ancora processati
  2. Per ogni TXT: legge header (TO, SUBJECT, ATTACHMENT, LANGUAGE)
     e corpo mail
  3. Trova il PDF corrispondente (ATTACHMENT header) nella stessa cartella
  4. Crea bozza Gmail con corpo + allegato PDF
  5. Sposta il TXT in sottocartella "processed/" di Drive A6
  6. Aggiorna stato A7 su Supabase

Formato atteso TXT (mail_NOMEAZIENDA_YYYYMMDD.txt):
  TO: marketing@azienda.com
  SUBJECT: Oggetto della mail
  ATTACHMENT: media_kit_NOMEAZIENDA.pdf
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
DRIVE_FOLDER_A6   = os.environ['DRIVE_FOLDER_A6']   # 1tHFoyvKc9ClKOWbcq5jsk28oC2iVfjB4
GMAIL_CLIENT_ID   = os.environ['GMAIL_CLIENT_ID']
GMAIL_CLIENT_SECRET = os.environ['GMAIL_CLIENT_SECRET']
GMAIL_REFRESH_TOKEN = os.environ['GMAIL_REFRESH_TOKEN']
GOOGLE_CREDENTIALS  = os.environ['GOOGLE_CREDENTIALS']  # service account JSON per Drive
SUPABASE_URL      = os.environ['SUPABASE_URL']
SUPABASE_KEY      = os.environ['SUPABASE_KEY']
GMAIL_FROM        = 'giandcdalcorso11@gmail.com'
PROCESSED_FOLDER_NAME = 'processed'


# ── DRIVE CLIENT (service account) ──────────────────────────────────
def get_drive_service():
    import tempfile
    from google.oauth2 import service_account

    creds_info = json.loads(GOOGLE_CREDENTIALS)
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
def get_or_create_processed_folder(drive, parent_id):
    """Trova o crea la sottocartella 'processed' in Drive A6."""
    res = drive.files().list(
        q=f"name='{PROCESSED_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' "
          f"and '{parent_id}' in parents and trashed=false",
        fields='files(id,name)'
    ).execute()

    files = res.get('files', [])
    if files:
        return files[0]['id']

    folder = drive.files().create(
        body={
            'name': PROCESSED_FOLDER_NAME,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        },
        fields='id'
    ).execute()
    print(f"Creata cartella 'processed': {folder['id']}")
    return folder['id']


def list_pending_txt(drive, folder_id, processed_folder_id):
    """Lista i file mail_*.txt che NON sono ancora nella cartella processed."""
    res = drive.files().list(
        q=f"name contains 'mail_' and name contains '.txt' "
          f"and '{folder_id}' in parents and trashed=false "
          f"and mimeType='text/plain'",
        fields='files(id,name,createdTime)'
    ).execute()
    return res.get('files', [])


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


def find_pdf_in_folder(drive, folder_id, pdf_name):
    """Cerca un PDF per nome nella cartella Drive A6."""
    res = drive.files().list(
        q=f"name='{pdf_name}' and '{folder_id}' in parents and trashed=false",
        fields='files(id,name)'
    ).execute()
    files = res.get('files', [])
    return files[0]['id'] if files else None


def move_to_processed(drive, file_id, processed_folder_id, parent_folder_id):
    """Sposta il TXT nella cartella 'processed'."""
    drive.files().update(
        fileId=file_id,
        addParents=processed_folder_id,
        removeParents=parent_folder_id,
        fields='id,parents'
    ).execute()


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
def create_gmail_draft(gmail, to_addr, subject, body_text, pdf_bytes=None, pdf_filename=None):
    """Crea una bozza Gmail con eventuale allegato PDF."""
    if pdf_bytes:
        msg = MIMEMultipart()
        msg['to'] = to_addr
        msg['from'] = GMAIL_FROM
        msg['subject'] = subject
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

        attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
        attachment.add_header(
            'Content-Disposition', 'attachment',
            filename=pdf_filename or 'media_kit.pdf'
        )
        msg.attach(attachment)
    else:
        msg = MIMEText(body_text, 'plain', 'utf-8')
        msg['to'] = to_addr
        msg['from'] = GMAIL_FROM
        msg['subject'] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = gmail.users().drafts().create(
        userId='me',
        body={'message': {'raw': raw}}
    ).execute()
    return draft['id']


# ── SUPABASE ─────────────────────────────────────────────────────────
def update_supabase_state(stato):
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
    }
    payload = {
        'stato': stato,
        'updated_at': datetime.now(timezone.utc).isoformat()
    }
    url = f"{SUPABASE_URL}/rest/v1/agent_states?agent_id=eq.a7"
    r = requests.patch(url, json=payload, headers=headers, timeout=10)
    if r.status_code not in (200, 204):
        print(f"Warning Supabase: {r.status_code} {r.text}")


# ── MAIN ─────────────────────────────────────────────────────────────
def main():
    print(f"[A7] Start — {datetime.now(timezone.utc).isoformat()}")

    drive = get_drive_service()
    gmail = get_gmail_service()

    # Trova o crea cartella processed
    processed_id = get_or_create_processed_folder(drive, DRIVE_FOLDER_A6)

    # Lista TXT in attesa
    pending = list_pending_txt(drive, DRIVE_FOLDER_A6, processed_id)
    print(f"[A7] File TXT in attesa: {len(pending)}")

    if not pending:
        print("[A7] Nessun file da processare. Exit.")
        return

    update_supabase_state('in_corso')
    drafts_created = 0
    errors = 0

    for file_info in pending:
        file_id = file_info['id']
        file_name = file_info['name']
        print(f"\n[A7] Processo: {file_name}")

        try:
            # Scarica e parsa il TXT
            content = download_file_text(drive, file_id)
            headers, body = parse_mail_txt(content)

            to_addr = headers.get('TO', '')
            subject = headers.get('SUBJECT', '(nessun oggetto)')
            attachment_name = headers.get('ATTACHMENT', '')

            if not to_addr:
                print(f"  SKIP: campo TO mancante in {file_name}")
                errors += 1
                continue

            print(f"  TO: {to_addr}")
            print(f"  SUBJECT: {subject}")
            print(f"  ATTACHMENT: {attachment_name or 'nessuno'}")

            # Cerca il PDF allegato
            pdf_bytes = None
            if attachment_name:
                pdf_id = find_pdf_in_folder(drive, DRIVE_FOLDER_A6, attachment_name)
                if pdf_id:
                    pdf_bytes = download_file_bytes(drive, pdf_id)
                    print(f"  PDF trovato: {attachment_name} ({len(pdf_bytes)//1024} KB)")
                else:
                    print(f"  Warning: PDF '{attachment_name}' non trovato in Drive A6")

            # Crea bozza Gmail
            draft_id = create_gmail_draft(
                gmail,
                to_addr=to_addr,
                subject=subject,
                body_text=body,
                pdf_bytes=pdf_bytes,
                pdf_filename=attachment_name or None
            )
            print(f"  Bozza Gmail creata: {draft_id}")

            # Sposta TXT in processed
            move_to_processed(drive, file_id, processed_id, DRIVE_FOLDER_A6)
            print(f"  Spostato in processed/")

            drafts_created += 1

        except Exception as e:
            print(f"  ERRORE su {file_name}: {e}")
            errors += 1

    print(f"\n[A7] Fine — {drafts_created} bozze create, {errors} errori")

    if errors == 0:
        update_supabase_state('done')
    elif drafts_created > 0:
        update_supabase_state('done')  # parziale ma OK
    else:
        update_supabase_state('idle')


if __name__ == '__main__':
    main()
