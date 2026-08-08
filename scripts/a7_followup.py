#!/usr/bin/env python3
"""
GDC IA TEAM — Agente 7 Follow-up — Bozze automatiche di sollecito
Trigger: cron giornaliero (vedi a7_followup.yml). Nessun input manuale.

ISOLAMENTO DA A7 (a7_gmail_drafter.py) — IMPORTANTE:
Questo script è stato progettato per non poter mai bloccare o interferire
con A7 in fase di generazione bozze:
  1. Pattern file diversi: A7 cerca SOLO 'mail_*.txt' (find_all_txt_in_files
     usa startswith('mail_')). Questo script cerca SOLO
     'followup{N}_*.txt' — i due insiemi di file non si intersecano mai,
     quindi non c'è mai un file conteso tra i due script.
  2. Campi Supabase separati: questo script scrive solo followup_count,
     followup_last_date, e chiavi step_notes con prefisso 'fu' — non
     tocca mai step_attuale, step_6, step_6_date, a7_status, a7_draft_id,
     a7_processed_file_id (di competenza esclusiva di A7).
  3. Workflow GitHub Actions indipendente: trigger diverso (schedule vs
     workflow_dispatch), nessun 'concurrency group' condiviso con
     "A7 — Gmail Drafter" — GitHub Actions non mette mai in coda l'uno
     in attesa dell'altro.
  4. Non itera MAI su tutte le aziende alla cieca: filtra sempre e solo
     step_attuale=7 (uguaglianza stretta, non >=7) — non tocca aziende
     in altri stadi della pipeline.

Flusso:
  1. Legge da Supabase tutte le companies con step_attuale=7,
     followup_stopped=false, followup_count < followup_max
  2. Per ciascuna, calcola i giorni dall'ultimo tocco
     (followup_last_date se presente, altrimenti step_7_date)
  3. Se giorni >= FOLLOWUP_CADENZA_GIORNI (default 5): cerca in Drive
     (stessa cartella azienda risolta via drive_folder_azienda, stessa
     logica di A7) il file 'followup{count+1}_[AZIENDA]_*.txt'
  4. Trovato → crea bozza Gmail (PDF allegato SOLO se il TXT ha
     l'header ATTACHMENT — un follow-up non deve riallegare il media kit
     per default, sembrerebbe spam), rinomina 'OK_', aggiorna
     followup_count/followup_last_date/step_notes, notifica push.
  5. NON trovato → NESSUNA generazione automatica di contenuto: logga
     un avviso ("manca il testo del follow-up N") e passa all'azienda
     successiva. Il principio di fondo è che tutto quello che parte è
     stato scritto e rivisto da Gianluca (nella stessa sessione A6.2 in
     cui scrive la mail originale), mai generato da questo script.
  6. Se followup_count raggiunge followup_max dopo l'invio: la company
     smette semplicemente di comparire nella query del punto 1 (nessun
     azzeramento, nessuna modifica a step_attuale) — resta a step 7 in
     attesa di gestione manuale/chiusura.

Formato TXT (identico a quello di A7, header ATTACHMENT opzionale):
  TO: email@azienda.com
  SUBJECT: Oggetto del follow-up
  ATTACHMENT: media_kit_[AZIENDA].pdf     (opzionale)
  LANGUAGE: IT

  Corpo del follow-up qui.
"""

import os
import sys
import base64
import json
import io
from datetime import datetime, timezone

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pywebpush import webpush, WebPushException


# ── CONFIG ──────────────────────────────────────────────────────────
GMAIL_CLIENT_ID         = os.environ['GMAIL_CLIENT_ID']
GMAIL_CLIENT_SECRET     = os.environ['GMAIL_CLIENT_SECRET']
GMAIL_REFRESH_TOKEN     = os.environ['GMAIL_REFRESH_TOKEN']
GOOGLE_CREDENTIALS      = os.environ['GOOGLE_CREDENTIALS']  # base64-encoded service account JSON
SUPABASE_URL            = os.environ['SUPABASE_URL']
SUPABASE_KEY            = os.environ['SUPABASE_SERVICE_KEY']
VAPID_PRIV              = os.environ['VAPID_PRIVATE_KEY']
VAPID_EMAIL             = os.environ['VAPID_EMAIL']
GMAIL_FROM              = 'giandcdalcorso11@gmail.com'
WEBAPP_BASE             = 'https://giandcdalcorso11-coder.github.io/GDC-DASHBOARD'

# Cadenza in giorni tra un follow-up e l'altro. Override manuale possibile
# via variabile d'ambiente (stesso pattern di BPT_TARGET_MONTH), utile per
# un test one-off senza aspettare 5 giorni veri.
FOLLOWUP_CADENZA_GIORNI = int(os.environ.get('FOLLOWUP_CADENZA_GIORNI') or '5')


# ── DRIVE CLIENT (service account) ──────────────────────────────────
def get_drive_service():
    from google.oauth2 import service_account
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


# ── DRIVE HELPERS (identici ad a7_gmail_drafter.py, riuso 1:1) ──────
def extract_drive_folder_id(url_or_id):
    if not url_or_id:
        return None
    url_or_id = url_or_id.strip()
    if '/folders/' in url_or_id:
        tail = url_or_id.split('/folders/', 1)[1]
        return tail.split('?')[0].split('/')[0]
    if '/' not in url_or_id:
        return url_or_id
    return None


def resolve_company_folder_id(drive, drive_folder_azienda):
    folder_id = extract_drive_folder_id(drive_folder_azienda)
    if not folder_id:
        return None
    try:
        meta = drive.files().get(
            fileId=folder_id, fields='id,name,mimeType,trashed'
        ).execute()
    except Exception as e:
        print(f"[A7-FU]   drive_folder_azienda presente ma non risolvibile ({folder_id}): {e}")
        return None
    if meta.get('trashed') or meta.get('mimeType') != 'application/vnd.google-apps.folder':
        return None
    return folder_id


def list_files_in_folder(drive, folder_id):
    res = drive.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields='files(id,name,mimeType,createdTime)'
    ).execute()
    return res.get('files', [])


def find_followup_txt(files, n):
    """Cerca il file followup{n}_*.txt tra i file listati. 'OK_' esclude
    quelli già processati (stesso meccanismo di A7)."""
    prefix = f"followup{n}_"
    matches = [f for f in files if f['name'].startswith(prefix) and f['name'].endswith('.txt')]
    if not matches:
        return None
    matches.sort(key=lambda f: f.get('createdTime', ''))
    return matches[0]


def find_pdf_for_attachment(files, attachment_name):
    pdfs = [f for f in files if f['mimeType'] == 'application/pdf']
    if not pdfs:
        return None
    if attachment_name:
        for f in pdfs:
            if f['name'] == attachment_name.strip():
                return f
    return None  # follow-up: nessun fallback automatico sul PDF più recente — solo se richiesto esplicitamente


def mark_txt_processed(drive, file_id, current_name):
    if current_name.startswith('OK_'):
        return
    new_name = 'OK_' + current_name
    try:
        drive.files().update(fileId=file_id, body={'name': new_name}).execute()
        print(f"[A7-FU]   TXT rinominato: {current_name} → {new_name}")
    except Exception as e:
        print(f"[A7-FU]   Warning: impossibile rinominare {current_name}: {e}")


def download_file_text(drive, file_id):
    request = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue().decode('utf-8')


def download_file_bytes(drive, file_id):
    request = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


# ── TXT PARSER (identico ad A7) ─────────────────────────────────────
def parse_mail_txt(content):
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


# ── GMAIL DRAFT (con allegato opzionale, a differenza di A7) ───────
def create_gmail_draft(gmail, to_addr, subject, body_text, pdf_bytes=None, pdf_filename=None):
    msg = MIMEMultipart()
    msg['to'] = to_addr
    msg['from'] = GMAIL_FROM
    msg['subject'] = subject
    msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

    if pdf_bytes:
        attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
        attachment.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
        msg.attach(attachment)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = gmail.users().drafts().create(
        userId='me', body={'message': {'raw': raw}}
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


def get_due_companies():
    """Aziende candidate al prossimo follow-up: step 7 esatto, non
    fermate manualmente, sotto il tetto massimo. Il filtro sui giorni
    trascorsi viene fatto in Python (serve confrontare due possibili
    campi data)."""
    url = (
        f"{SUPABASE_URL}/rest/v1/companies"
        f"?step_attuale=eq.7&followup_stopped=eq.false"
        f"&select=id,nome,drive_folder_azienda,step_7_date,"
        f"followup_count,followup_last_date,followup_max,step_notes"
    )
    r = requests.get(url, headers=supabase_headers(), timeout=10)
    if r.status_code != 200:
        print(f"[A7-FU] Errore lettura companies: {r.status_code} {r.text}")
        return []
    rows = r.json()
    return [row for row in rows if (row.get('followup_count') or 0) < (row.get('followup_max') or 3)]


def days_since(iso_date):
    if not iso_date:
        return None
    dt = datetime.fromisoformat(iso_date.replace('Z', '+00:00'))
    return (datetime.now(timezone.utc) - dt).days


def update_company_followup(company_id, new_count, note_key, note_text, existing_notes):
    notes = dict(existing_notes or {})
    notes[note_key] = note_text
    payload = {
        'followup_count': new_count,
        'followup_last_date': datetime.now(timezone.utc).isoformat(),
        'step_notes': notes,
    }
    url = f"{SUPABASE_URL}/rest/v1/companies?id=eq.{company_id}"
    r = requests.patch(url, json=payload, headers=supabase_headers(), timeout=10)
    if r.status_code not in (200, 204):
        print(f"[A7-FU]   Warning aggiornamento Supabase: {r.status_code} {r.text}")
    else:
        print(f"[A7-FU]   Supabase aggiornato: followup_count={new_count}")


def log_activity(agent_id, titolo, descrizione, link):
    payload = {
        'agent_id': agent_id, 'tipo': 'step',
        'titolo': titolo, 'descrizione': descrizione, 'link': link,
    }
    r = requests.post(f"{SUPABASE_URL}/rest/v1/activity_log", json=payload, headers=supabase_headers(), timeout=10)
    if r.status_code not in (200, 201, 204):
        print(f"[A7-FU]   Warning activity_log: {r.status_code} {r.text}")


def get_push_subscriptions():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/push_subscriptions?select=endpoint,p256dh,auth,device_label",
        headers=supabase_headers(), timeout=10
    )
    return r.json() if r.status_code == 200 else []


def delete_subscription(endpoint):
    requests.delete(f"{SUPABASE_URL}/rest/v1/push_subscriptions?endpoint=eq.{endpoint}",
                     headers=supabase_headers(), timeout=10)


def send_push_all(title, body, url):
    subs = get_push_subscriptions()
    if not subs:
        print("[A7-FU]   Push: nessun dispositivo registrato — skip.")
        return
    for sub in subs:
        label = sub.get('device_label') or sub['endpoint'][:40]
        subscription_info = {'endpoint': sub['endpoint'], 'keys': {'p256dh': sub['p256dh'], 'auth': sub['auth']}}
        try:
            webpush(
                subscription_info=subscription_info,
                data=json.dumps({'title': title, 'body': body, 'url': url}),
                vapid_private_key=VAPID_PRIV,
                vapid_claims={'sub': f"mailto:{VAPID_EMAIL}"}
            )
            print(f"[A7-FU]   Push inviata a '{label}'")
        except WebPushException as e:
            status = getattr(e.response, 'status_code', None)
            print(f"[A7-FU]   Push fallita per '{label}' (status {status}): {e}")
            if status in (404, 410):
                delete_subscription(sub['endpoint'])


# ── MAIN ─────────────────────────────────────────────────────────────
def main():
    print(f"[A7-FU] Start — {datetime.now(timezone.utc).isoformat()} — cadenza {FOLLOWUP_CADENZA_GIORNI}gg")

    companies = get_due_companies()
    print(f"[A7-FU] Aziende candidate (step 7, non fermate, sotto il tetto): {len(companies)}")

    if not companies:
        print("[A7-FU] Nessuna azienda candidata. Fine.")
        return

    drive = get_drive_service()
    gmail = get_gmail_service()

    processed = 0
    missing_txt = []
    errors = []

    for co in companies:
        nome = co['nome']
        count = co.get('followup_count') or 0
        next_n = count + 1
        last_touch = co.get('followup_last_date') or co.get('step_7_date')
        gg = days_since(last_touch)

        if gg is None or gg < FOLLOWUP_CADENZA_GIORNI:
            print(f"[A7-FU] {nome}: non ancora in cadenza ({gg}gg su {FOLLOWUP_CADENZA_GIORNI}gg richiesti) — skip.")
            continue

        print(f"[A7-FU] {nome}: dovuto follow-up #{next_n} ({gg}gg dall'ultimo tocco).")

        folder_id = resolve_company_folder_id(drive, co.get('drive_folder_azienda'))
        if not folder_id:
            print(f"[A7-FU]   ERRORE: drive_folder_azienda assente/non risolvibile per '{nome}' — skip.")
            errors.append(nome)
            continue

        files = list_files_in_folder(drive, folder_id)
        txt_file = find_followup_txt(files, next_n)

        if not txt_file:
            print(f"[A7-FU]   Manca il testo 'followup{next_n}_...' in Drive per '{nome}' — nessuna generazione automatica, skip.")
            missing_txt.append(f"{nome} (follow-up {next_n})")
            continue

        try:
            txt_content = download_file_text(drive, txt_file['id'])
            headers, body = parse_mail_txt(txt_content)
            to_addr = headers.get('TO', '').strip()
            subject = headers.get('SUBJECT', '(nessun oggetto)').strip()
            attachment_name = headers.get('ATTACHMENT', '').strip()

            if not to_addr:
                print(f"[A7-FU]   ERRORE: campo TO mancante in {txt_file['name']} — skip.")
                errors.append(nome)
                continue

            pdf_bytes, pdf_filename = None, None
            if attachment_name:
                pdf_file = find_pdf_for_attachment(files, attachment_name)
                if pdf_file:
                    pdf_bytes = download_file_bytes(drive, pdf_file['id'])
                    pdf_filename = pdf_file['name']
                else:
                    print(f"[A7-FU]   Attenzione: ATTACHMENT '{attachment_name}' indicato ma non trovato — bozza senza allegato.")

            draft_id = create_gmail_draft(gmail, to_addr, subject, body, pdf_bytes, pdf_filename)
            print(f"[A7-FU]   Bozza creata: {draft_id} (TO: {to_addr})")

            mark_txt_processed(drive, txt_file['id'], txt_file['name'])
            update_company_followup(
                co['id'], next_n,
                note_key=f"7_fu{next_n}",
                note_text=f"Follow-up {next_n} — bozza Gmail creata (draft_id={draft_id}).",
                existing_notes=co.get('step_notes')
            )

            link = f"{WEBAPP_BASE}/page_company_v2.html?id={co['id']}"
            log_activity('A7', f"{nome} — Follow-up {next_n}", "Bozza di sollecito pronta su Gmail.", link)
            send_push_all(f"{nome} — Follow-up {next_n} pronto", "Apri Gmail e controlla prima di inviare.", link)

            processed += 1

        except Exception as e:
            print(f"[A7-FU]   ERRORE imprevisto su '{nome}': {e}")
            import traceback
            traceback.print_exc()
            errors.append(nome)
            continue

    print(f"[A7-FU] Fine — {processed} follow-up creati, {len(missing_txt)} testi mancanti, {len(errors)} errori.")
    if missing_txt:
        print(f"[A7-FU] Testi mancanti: {missing_txt}")
    if errors:
        print(f"[A7-FU] Errori: {errors}")

    # Se ci sono testi mancanti, un run "fallito" farebbe scattare
    # notify_failures inutilmente (non è un crash, è solo lavoro da fare
    # per Gianluca). Notifichiamo qui, direttamente, senza sys.exit(1).
    if missing_txt:
        send_push_all(
            "Follow-up in attesa di testo",
            f"{len(missing_txt)} follow-up pronti per essere scritti: " + ", ".join(missing_txt[:5]),
            f"{WEBAPP_BASE}/page_pipeline_v1.html"
        )

    # Un vero errore tecnico (Drive irraggiungibile, folder non risolta,
    # ecc.) fa fallire il workflow per davvero, così notify_failures lo
    # intercetta come rete di sicurezza.
    if errors and not processed and not missing_txt:
        sys.exit(1)


if __name__ == '__main__':
    main()
