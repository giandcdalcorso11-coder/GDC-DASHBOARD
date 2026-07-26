#!/usr/bin/env python3
"""
GDC IA TEAM — Agente 7 — Gmail Drafter
Trigger: workflow_dispatch da home webapp con parametro company_name.

Flusso:
  1. Riceve company_name come parametro
  2. Trova la cartella azienda in Drive A6/Aziende/ — PRIMA prova a leggere
     drive_folder_azienda da Supabase e usare l'ID diretto; solo se assente
     o non piu' valido, ripiega sulla vecchia ricerca per nome esatto
     cartella == company_name (v4, Luglio 2026 — vedi nota sotto)
  3. Cerca TUTTI i file mail_*.txt nella cartella (non solo il piu' recente)
     e il/i PDF presenti
  4. Se nessun PDF: stop con errore
  5. Per OGNI TXT trovato: crea una bozza Gmail separata (stesso PDF
     allegato a tutte, salvo match specifico per nome — vedi sotto).
     Dopo la creazione riuscita, il TXT viene rinominato su Drive con
     prefisso "OK_" cosi' un rilancio successivo non lo rielabora e non
     duplica bozze gia' create (v4, Luglio 2026)
  6. Aggiorna Supabase companies (a7_status, a7_processed_at, a7_draft_id,
     a7_processed_file_id — questi ultimi due come lista comma-separata
     se sono state create piu' bozze nello stesso run)
  7. Aggiorna Supabase companies — pipeline step 6 "Bozza Gmail" (step_6, step_6_date, step_notes,
     step_attuale se non gia' avanzato oltre da Gianluca) — v2, Luglio 2026
  8. Aggiorna Supabase agent_states (stato a7)

Formato TXT (mail_[AZIENDA]_YYYY-MM-DD.txt, o mail_[AZIENDA]_[qualsiasi].txt
per distinguere piu' destinatari della stessa azienda):
  TO: email@azienda.com
  SUBJECT: Oggetto della mail
  ATTACHMENT: media_kit_[AZIENDA].pdf
  LANGUAGE: IT

  Corpo della mail qui.
  Tutto il testo.
  Firma inclusa.

Nota sulla ricerca cartella Drive (v4, Luglio 2026):
  In precedenza la cartella azienda veniva cercata SOLO per nome esatto
  (name == company_name) dentro A6/Aziende/. Se il nome della cartella su
  Drive non coincideva esattamente col nome azienda in Supabase (es.
  cartella creata a mano con un nome abbreviato), A7 falliva anche se la
  cartella esisteva ed era correttamente linkata in drive_folder_azienda.
  Ora lo script legge prima quel campo e usa l'ID diretto: il nome
  cartella puo' divergere da quello Supabase senza causare errori.

Nota su piu' TXT nella stessa cartella (v4, Luglio 2026):
  Caso reale: due tentativi con due destinatari diversi per la stessa
  azienda (es. De Cecco) salvati come due file mail_*.txt distinti. Prima
  A7 processava solo il piu' recente e ignorava l'altro in silenzio. Ora
  crea una bozza per ciascuno e rinomina i TXT processati con prefisso
  "OK_" cosi' restano nella cartella come storico ma non vengono
  ripescati da un rilancio successivo (che processerebbe solo eventuali
  NUOVI TXT aggiunti dopo).

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
def extract_drive_folder_id(url_or_id):
    """
    Estrae l'ID cartella da un URL tipo
    'https://drive.google.com/drive/folders/XXXX' oppure, se la stringa
    e' gia' un ID nudo (nessuno slash), la ritorna cosi' com'e'.
    Ritorna None se url_or_id e' vuoto/assente.
    """
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
    """
    Verifica che l'ID estratto da drive_folder_azienda punti davvero a
    una cartella Drive esistente e non cestinata. Ritorna l'ID se valido,
    altrimenti None (per far ripiegare il chiamante sulla ricerca per nome).
    """
    folder_id = extract_drive_folder_id(drive_folder_azienda)
    if not folder_id:
        return None
    try:
        meta = drive.files().get(
            fileId=folder_id,
            fields='id,name,mimeType,trashed'
        ).execute()
    except Exception as e:
        print(f"[A7] drive_folder_azienda presente ma non risolvibile ({folder_id}): {e}")
        return None
    if meta.get('trashed'):
        print(f"[A7] Cartella da drive_folder_azienda risulta cestinata ({folder_id})")
        return None
    if meta.get('mimeType') != 'application/vnd.google-apps.folder':
        print(f"[A7] drive_folder_azienda non punta a una cartella ({folder_id})")
        return None
    print(f"[A7] Cartella azienda risolta via drive_folder_azienda: '{meta.get('name')}' ({folder_id})")
    return folder_id


def find_company_folder_by_name(drive, aziende_folder_id, company_name):
    """Fallback: trova la sottocartella [NOME AZIENDA] dentro A6/Aziende/
    cercando per nome esatto (comportamento storico, pre-v4)."""
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


def find_all_txt_in_files(files):
    """
    Trova TUTTI i file mail_*.txt tra i file listati (non solo il più
    recente) — caso reale: più tentativi con destinatari diversi per la
    stessa azienda. Un file già processato viene rinominato con prefisso
    "OK_" (vedi mark_txt_processed) e quindi non compare più qui, perché
    "OK_mail_..." non soddisfa più startswith('mail_').
    Ordinati per data creazione crescente (il più vecchio per primo),
    così le bozze vengono create nell'ordine in cui i tentativi sono
    stati scritti.
    """
    txts = [f for f in files if f['name'].startswith('mail_') and f['name'].endswith('.txt')]
    txts.sort(key=lambda f: f.get('createdTime', ''))
    return txts


def find_pdf_in_files(files):
    """Trova il file PDF più recente tra i file listati (fallback quando
    non c'è un match per nome con l'header ATTACHMENT)."""
    pdfs = [f for f in files if f['mimeType'] == 'application/pdf']
    if not pdfs:
        return None
    pdfs.sort(key=lambda f: f.get('createdTime', ''), reverse=True)
    return pdfs[0]


def find_pdf_for_attachment(files, attachment_name):
    """
    Cerca tra i PDF della cartella quello il cui nome combacia con
    l'header ATTACHMENT del TXT (utile quando ci sono più PDF, es. media
    kit in lingue diverse). Se non c'è match, ripiega sul PDF più
    recente — stesso comportamento di prima per il caso comune di un
    solo PDF in cartella.
    """
    pdfs = [f for f in files if f['mimeType'] == 'application/pdf']
    if not pdfs:
        return None
    if attachment_name:
        for f in pdfs:
            if f['name'] == attachment_name.strip():
                return f
    pdfs.sort(key=lambda f: f.get('createdTime', ''), reverse=True)
    return pdfs[0]


def mark_txt_processed(drive, file_id, current_name):
    """
    Rinomina il TXT appena processato con prefisso 'OK_' così un
    rilancio successivo di A7 sulla stessa azienda non lo rielabora
    (find_all_txt_in_files cerca solo nomi che iniziano per 'mail_').
    Il file resta in cartella come storico, solo rinominato.
    """
    if current_name.startswith('OK_'):
        return
    new_name = 'OK_' + current_name
    try:
        drive.files().update(fileId=file_id, body={'name': new_name}).execute()
        print(f"[A7] TXT rinominato per evitare riprocessamento: {current_name} → {new_name}")
    except Exception as e:
        print(f"[A7] Warning: impossibile rinominare {current_name} dopo il processamento: {e}")


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


def _joined(value):
    """Se value è una lista, la unisce in stringa comma-separata (per
    salvare più draft_id/file_id in una singola colonna text); se è già
    una stringa, la ritorna invariata."""
    if isinstance(value, (list, tuple)):
        return ','.join(str(v) for v in value)
    return value


def update_company_a7(company_name, status, draft_id=None, file_id=None):
    """Aggiorna le colonne a7_* nella tabella companies per questa azienda.
    draft_id e file_id accettano sia una stringa singola sia una lista
    (caso multi-TXT: più bozze create nello stesso run)."""
    row, err = find_company_row(company_name, select='id,nome')
    if err:
        print(f"[A7] Nessun aggiornamento a7_status per '{company_name}' ({err})")
        return

    payload = {
        'a7_status': status,
        'a7_processed_at': datetime.now(timezone.utc).isoformat(),
    }
    if draft_id:
        payload['a7_draft_id'] = _joined(draft_id)
    if file_id:
        payload['a7_processed_file_id'] = _joined(file_id)

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

def update_pipeline_step_6(company_name, draft_ids):
    """
    Avanza la pipeline a step 6 (Bozza Gmail) dopo la creazione della bozza.
    Non retrocede mai: se step_attuale e' gia' >= 6 (Gianluca ha avanzato
    oltre a mano), lascia step_attuale invariato ma aggiorna comunque
    step_6 / step_6_date / step_notes per coerenza della timeline.
    draft_ids: lista di draft_id creati in questo run (anche di un solo
    elemento) — la nota riporta quante bozze sono state generate quando
    sono più di una (caso multi-TXT / più destinatari).
    """
    row, err = find_company_row(company_name, select='id,nome,step_attuale,step_6_date,step_notes')
    if err:
        print(f"[A7] Impossibile aggiornare step 6 per '{company_name}' ({err})")
        return

    current_step = row.get('step_attuale') or 0
    step_6_date = datetime.now(timezone.utc).isoformat()
    notes = row.get('step_notes') or {}
    if len(draft_ids) > 1:
        notes['6'] = f"{len(draft_ids)} bozze Gmail create (draft_id={','.join(draft_ids)})."
    else:
        notes['6'] = f"Bozza Gmail creata (draft_id={draft_ids[0]})."

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
        #    v4: prima prova l'ID diretto da drive_folder_azienda (Supabase),
        #    poi ripiega sulla vecchia ricerca per nome esatto.
        company_folder_id = None
        row, row_err = find_company_row(COMPANY_NAME, select='id,nome,drive_folder_azienda')
        if row_err == 'ambiguous':
            print(f"[A7] ERRORE: nome azienda ambiguo, impossibile procedere in sicurezza.")
            update_agent_state('idle')
            sys.exit(1)
        if row and not row_err:
            company_folder_id = resolve_company_folder_id(drive, row.get('drive_folder_azienda'))

        if not company_folder_id:
            print(f"[A7] Nessuna cartella risolta via drive_folder_azienda, provo ricerca per nome...")
            company_folder_id = find_company_folder_by_name(drive, DRIVE_FOLDER_A6_AZIENDE, COMPANY_NAME)

        if not company_folder_id:
            msg = f"Cartella '{COMPANY_NAME}' non trovata né via drive_folder_azienda né per nome in Drive A6/Aziende/"
            print(f"[A7] ERRORE: {msg}")
            update_agent_state('idle')
            update_company_a7(COMPANY_NAME, 'error')
            sys.exit(1)

        print(f"[A7] Cartella azienda: {company_folder_id}")

        # 2. Lista file nella cartella
        files = list_files_in_folder(drive, company_folder_id)
        print(f"[A7] File trovati nella cartella: {[f['name'] for f in files]}")

        # 3. Trova TUTTI i TXT (mail_*.txt) — caso multi-destinatario
        txt_files = find_all_txt_in_files(files)
        if not txt_files:
            print(f"[A7] ERRORE: nessun file mail_*.txt trovato in A6/Aziende/{COMPANY_NAME}/")
            update_agent_state('idle')
            update_company_a7(COMPANY_NAME, 'error')
            sys.exit(1)

        print(f"[A7] TXT da processare ({len(txt_files)}): {[f['name'] for f in txt_files]}")

        # 4. Serve almeno un PDF — se assente: stop (nessuna bozza può
        #    essere creata senza allegato)
        if not any(f['mimeType'] == 'application/pdf' for f in files):
            print(f"[A7] ERRORE: nessun PDF trovato in A6/Aziende/{COMPANY_NAME}/")
            print(f"[A7] Caricare il PDF prima di lanciare A7.")
            update_agent_state('idle')
            update_company_a7(COMPANY_NAME, 'error')
            sys.exit(1)

        # 5. Loop: una bozza per ogni TXT trovato
        created_draft_ids = []
        processed_file_ids = []
        failed_txts = []
        pdf_cache = {}  # file_id -> bytes, per non riscaricare lo stesso PDF più volte

        for txt_file in txt_files:
            print(f"[A7] — Processando: {txt_file['name']}")
            try:
                txt_content = download_file_text(drive, txt_file['id'])
                headers, body = parse_mail_txt(txt_content)

                to_addr = headers.get('TO', '').strip()
                subject = headers.get('SUBJECT', '(nessun oggetto)').strip()
                attachment_name = headers.get('ATTACHMENT', '').strip()

                if not to_addr:
                    print(f"[A7]   ERRORE: campo TO mancante in {txt_file['name']}, salto questo file.")
                    failed_txts.append(txt_file['name'])
                    continue

                pdf_file = find_pdf_for_attachment(files, attachment_name)
                if not pdf_file:
                    print(f"[A7]   ERRORE: nessun PDF disponibile per {txt_file['name']}, salto questo file.")
                    failed_txts.append(txt_file['name'])
                    continue

                if pdf_file['id'] not in pdf_cache:
                    pdf_cache[pdf_file['id']] = download_file_bytes(drive, pdf_file['id'])
                pdf_bytes = pdf_cache[pdf_file['id']]

                print(f"[A7]   TO: {to_addr} | SUBJECT: {subject} | PDF: {pdf_file['name']} ({len(pdf_bytes)//1024} KB)")

                draft_id = create_gmail_draft(
                    gmail,
                    to_addr=to_addr,
                    subject=subject,
                    body_text=body,
                    pdf_bytes=pdf_bytes,
                    pdf_filename=pdf_file['name']
                )
                print(f"[A7]   Bozza Gmail creata: {draft_id}")

                mark_txt_processed(drive, txt_file['id'], txt_file['name'])

                created_draft_ids.append(draft_id)
                processed_file_ids.append(txt_file['id'])

            except Exception as e:
                print(f"[A7]   ERRORE imprevisto su {txt_file['name']}: {e}")
                failed_txts.append(txt_file['name'])
                continue

        # 6. Aggiorna Supabase in base all'esito complessivo
        if created_draft_ids and not failed_txts:
            status = 'drafted'
        elif created_draft_ids and failed_txts:
            status = 'drafted'  # parziale: almeno una bozza creata, ma segnalato in console
            print(f"[A7] ATTENZIONE: {len(failed_txts)} TXT non processati: {failed_txts}")
        else:
            status = 'error'

        update_company_a7(
            COMPANY_NAME,
            status=status,
            draft_id=created_draft_ids if created_draft_ids else None,
            file_id=processed_file_ids if processed_file_ids else None
        )

        if created_draft_ids:
            update_pipeline_step_6(COMPANY_NAME, created_draft_ids)

        update_agent_state('done' if created_draft_ids else 'idle')

        if not created_draft_ids:
            print(f"[A7] Fine — NESSUNA bozza creata per {COMPANY_NAME} (tutti i TXT falliti)")
            sys.exit(1)

        print(f"[A7] Fine — {len(created_draft_ids)} bozza/e creata/e per {COMPANY_NAME}"
              + (f" ({len(failed_txts)} falliti: {failed_txts})" if failed_txts else ""))

    except Exception as e:
        print(f"[A7] ERRORE imprevisto: {e}")
        import traceback
        traceback.print_exc()
        update_agent_state('idle')
        update_company_a7(COMPANY_NAME, 'error')
        sys.exit(1)


if __name__ == '__main__':
    main()
