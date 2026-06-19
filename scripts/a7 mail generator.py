"""
GDC IA TEAM — Script A7 Mail Generator
Polling ogni 15 minuti + trigger manuale dalla webapp.

Flusso:
1. Scansiona tutte le sottocartelle di AGENTE 6 / Aziende / [AZIENDA] /
2. Per ogni azienda: cerca mail_[AZIENDA]_[data].txt non ancora processato
3. Verifica che esista mediakit_[AZIENDA].pdf nella stessa cartella
4. Se entrambi presenti → crea bozza Gmail via Gmail API (delegation)
5. Aggiorna Supabase companies: a7_status, a7_processed_at, a7_draft_id
6. Invia push notification "Bozza pronta in Gmail"

Secrets GitHub richiesti:
  GOOGLE_CREDENTIALS  — JSON service account Google (base64)
  DRIVE_FOLDER_A6     — ID cartella AGENTE 6 (root con sottocartella Aziende)
  SUPABASE_URL        — URL progetto Supabase (.co)
  SUPABASE_KEY        — anon/service key Supabase
  GMAIL_DELEGATED_USER — giandcdalcorso11@gmail.com
"""

import os
import json
import base64
import re
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
from supabase import create_client


# ─── CONFIG ────────────────────────────────────────────────────────────────────

SUPA_URL          = os.environ["SUPABASE_URL"]
SUPA_KEY          = os.environ["SUPABASE_KEY"]
DRIVE_FOLDER_A6   = os.environ["DRIVE_FOLDER_A6"]
GMAIL_USER        = os.environ.get("GMAIL_DELEGATED_USER", "giandcdalcorso11@gmail.com")

# Sottocartella Aziende dentro A6
# Struttura: AGENTE 6 / Aziende / [AZIENDA] /
AZIENDE_SUBFOLDER_NAME = "Aziende"

print(f"▶ A7 Mail Generator — avvio {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
print(f"  Cartella A6: {DRIVE_FOLDER_A6}")
print(f"  Gmail delegation: {GMAIL_USER}")


# ─── GOOGLE DRIVE SERVICE ──────────────────────────────────────────────────────

def get_drive_service():
    creds_b64  = os.environ["GOOGLE_CREDENTIALS"]
    creds_json = json.loads(base64.b64decode(creds_b64))
    scopes     = ["https://www.googleapis.com/auth/drive.readonly"]
    creds      = Credentials.from_service_account_info(creds_json, scopes=scopes)
    return build("drive", "v3", credentials=creds)


# ─── GMAIL SERVICE (con delegation) ───────────────────────────────────────────

def get_gmail_service():
    """
    Crea servizio Gmail con domain-wide delegation.
    Il service account impersona giandcdalcorso11@gmail.com.
    Richiede:
    - Service account con domain-wide delegation abilitata
    - Scope gmail autorizzato in Google Workspace Admin (o Gmail settings)
    """
    creds_b64  = os.environ["GOOGLE_CREDENTIALS"]
    creds_json = json.loads(base64.b64decode(creds_b64))
    scopes     = ["https://www.googleapis.com/auth/gmail.compose"]
    creds      = Credentials.from_service_account_info(
        creds_json,
        scopes=scopes,
        subject=GMAIL_USER  # delegation: agisce come questo utente
    )
    return build("gmail", "v1", credentials=creds)


# ─── SUPABASE ─────────────────────────────────────────────────────────────────

def get_supabase():
    return create_client(SUPA_URL, SUPA_KEY)


def get_processed_files(supabase) -> set:
    """
    Restituisce l'insieme dei file TXT già processati da A7.
    Colonna: a7_processed_file_id (Drive file ID del txt processato).
    """
    result = supabase.table("companies") \
        .select("a7_processed_file_id") \
        .not_.is_("a7_processed_file_id", "null") \
        .execute()
    return {row["a7_processed_file_id"] for row in (result.data or [])}


def upsert_company_a7(supabase, nome_azienda: str, file_id_txt: str,
                      draft_id: str, status: str):
    """
    Aggiorna/inserisce lo stato A7 nella tabella companies.
    Usa nome_azienda come chiave di ricerca.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    supabase.table("companies").upsert({
        "nome":                   nome_azienda,
        "a7_status":              status,         # "draft_created" | "error" | "skipped_no_pdf"
        "a7_processed_at":        now_iso,
        "a7_processed_file_id":   file_id_txt,
        "a7_draft_id":            draft_id,
    }, on_conflict="nome").execute()
    print(f"    Supabase: {nome_azienda} → a7_status={status}")


# ─── DRIVE — SCANSIONE CARTELLE ───────────────────────────────────────────────

def find_aziende_folder(drive, parent_id: str) -> str | None:
    """Trova la cartella 'Aziende' dentro AGENTE 6."""
    query = (f"'{parent_id}' in parents "
             f"and mimeType='application/vnd.google-apps.folder' "
             f"and name='{AZIENDE_SUBFOLDER_NAME}' "
             f"and trashed=false")
    result = drive.files().list(
        q=query, fields="files(id, name)",
        supportsAllDrives=True, includeItemsFromAllDrives=True
    ).execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]
    print(f"  WARN: cartella '{AZIENDE_SUBFOLDER_NAME}' non trovata in A6")
    return None


def list_azienda_folders(drive, aziende_folder_id: str) -> list[dict]:
    """Elenca tutte le sottocartelle azienda dentro Aziende/."""
    query = (f"'{aziende_folder_id}' in parents "
             f"and mimeType='application/vnd.google-apps.folder' "
             f"and trashed=false")
    result = drive.files().list(
        q=query, fields="files(id, name)",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
        pageSize=100
    ).execute()
    return result.get("files", [])


def find_files_in_folder(drive, folder_id: str) -> list[dict]:
    """Elenca tutti i file (non cartelle) dentro una cartella azienda."""
    query = (f"'{folder_id}' in parents "
             f"and mimeType != 'application/vnd.google-apps.folder' "
             f"and trashed=false")
    result = drive.files().list(
        q=query,
        fields="files(id, name, mimeType, createdTime, modifiedTime)",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
        orderBy="createdTime desc"
    ).execute()
    return result.get("files", [])


def find_mail_txt(files: list[dict]) -> dict | None:
    """
    Cerca il file mail_[AZIENDA]_[data].txt più recente.
    Pattern: mail_*.txt (case insensitive)
    """
    candidates = [
        f for f in files
        if re.match(r'mail_.+\.txt$', f["name"], re.IGNORECASE)
    ]
    if not candidates:
        return None
    # Prende il più recente per data creazione
    candidates.sort(key=lambda f: f.get("createdTime", ""), reverse=True)
    return candidates[0]


def find_mediakit_pdf(files: list[dict], nome_azienda: str) -> dict | None:
    """
    Cerca il file mediakit_[AZIENDA].pdf.
    Pattern flessibile: mediakit_*.pdf o mediakit *.pdf (case insensitive)
    """
    azienda_lower = nome_azienda.lower().replace(" ", "").replace("-", "")
    for f in files:
        fname_lower = f["name"].lower()
        if fname_lower.endswith(".pdf") and "mediakit" in fname_lower:
            return f
    return None


# ─── DRIVE — LETTURA CONTENUTO TXT ────────────────────────────────────────────

def download_txt_content(drive, file_id: str) -> str:
    """Scarica e decodifica il contenuto di un file TXT da Drive."""
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue().decode("utf-8")


def parse_mail_txt(content: str) -> dict:
    """
    Parsa il file TXT con formato:
      Oggetto: [oggetto]
      Destinatario: [email]
      Corpo:
      [testo]

    Restituisce dict con chiavi: oggetto, destinatario, corpo
    """
    lines = content.strip().splitlines()
    result = {"oggetto": "", "destinatario": "", "corpo": ""}

    corpo_start = None
    for i, line in enumerate(lines):
        if line.lower().startswith("oggetto:"):
            result["oggetto"] = line[len("oggetto:"):].strip()
        elif line.lower().startswith("destinatario:"):
            result["destinatario"] = line[len("destinatario:"):].strip()
        elif line.lower().startswith("corpo:"):
            corpo_start = i + 1
            break

    if corpo_start is not None:
        result["corpo"] = "\n".join(lines[corpo_start:]).strip()

    return result


def download_pdf_bytes(drive, file_id: str) -> bytes:
    """Scarica un PDF da Drive come bytes."""
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


# ─── GMAIL — CREAZIONE BOZZA ──────────────────────────────────────────────────

def create_gmail_draft(gmail, mail_data: dict,
                       pdf_bytes: bytes, pdf_filename: str,
                       nome_azienda: str) -> str:
    """
    Crea una bozza Gmail con:
    - mittente: giandcdalcorso11@gmail.com (via delegation)
    - destinatario: dall'email nel TXT
    - oggetto: dall'oggetto nel TXT
    - corpo: testo della mail
    - allegato: PDF media kit

    Restituisce il draft ID.
    """
    msg = MIMEMultipart()
    msg["From"]    = GMAIL_USER
    msg["To"]      = mail_data["destinatario"]
    msg["Subject"] = mail_data["oggetto"]

    # Corpo testo
    msg.attach(MIMEText(mail_data["corpo"], "plain", "utf-8"))

    # Allegato PDF
    part = MIMEBase("application", "octet-stream")
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f'attachment; filename="{pdf_filename}"'
    )
    msg.attach(part)

    # Encode per Gmail API
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    draft = gmail.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}}
    ).execute()

    draft_id = draft.get("id", "")
    print(f"    ✅ Bozza Gmail creata: ID {draft_id}")
    print(f"       To: {mail_data['destinatario']}")
    print(f"       Oggetto: {mail_data['oggetto']}")
    print(f"       Allegato: {pdf_filename}")
    return draft_id


# ─── PUSH NOTIFICATION ────────────────────────────────────────────────────────

def send_push(nome_azienda: str, draft_id: str):
    """
    Invia push notification via Web Push API.
    Richiede secrets PUSH_SUBSCRIPTION, VAPID_PRIVATE_KEY, VAPID_EMAIL.
    """
    push_sub_raw  = os.environ.get("PUSH_SUBSCRIPTION", "")
    vapid_key     = os.environ.get("VAPID_PRIVATE_KEY", "")
    vapid_email   = os.environ.get("VAPID_EMAIL", "")

    if not push_sub_raw or not vapid_key:
        print("    WARN: Push non configurata (PUSH_SUBSCRIPTION o VAPID_PRIVATE_KEY mancanti)")
        return

    try:
        from pywebpush import webpush, WebPushException
        subscription_info = json.loads(push_sub_raw)
        payload = json.dumps({
            "title": "📧 Bozza Gmail pronta",
            "body":  f"{nome_azienda} — Apri Gmail per inviare",
            "icon":  "/icon-192.png",
            "data":  {"draft_id": draft_id, "azienda": nome_azienda}
        })
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=vapid_key,
            vapid_claims={"sub": f"mailto:{vapid_email}"}
        )
        print(f"    📱 Push inviata: {nome_azienda}")
    except Exception as e:
        print(f"    WARN: Push fallita — {e}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    drive    = get_drive_service()
    gmail    = get_gmail_service()
    supabase = get_supabase()

    # 1. Carica set file TXT già processati
    processed = get_processed_files(supabase)
    print(f"  File già processati in Supabase: {len(processed)}")

    # 2. Trova cartella Aziende dentro A6
    aziende_folder_id = find_aziende_folder(drive, DRIVE_FOLDER_A6)
    if not aziende_folder_id:
        print("  ERRORE: cartella Aziende non trovata — exit")
        return

    # 3. Elenca tutte le cartelle azienda
    azienda_folders = list_azienda_folders(drive, aziende_folder_id)
    print(f"  Aziende trovate in Drive: {len(azienda_folders)}")

    bozze_create = 0
    skip_no_pdf  = 0
    skip_already = 0

    # Filtro opzionale: se la webapp ha triggerato per una sola azienda
    filter_azienda = os.environ.get("A7_FILTER_AZIENDA", "").strip().upper()
    if filter_azienda:
        print(f"  Filtro azienda attivo: {filter_azienda}")
        azienda_folders = [f for f in azienda_folders
                           if f["name"].upper() == filter_azienda]
        if not azienda_folders:
            print(f"  WARN: azienda '{filter_azienda}' non trovata in Drive")

    for folder in azienda_folders:
        nome_azienda = folder["name"]
        folder_id    = folder["id"]

        files = find_files_in_folder(drive, folder_id)
        if not files:
            continue

        # Cerca TXT mail
        mail_file = find_mail_txt(files)
        if not mail_file:
            continue  # nessuna mail da processare per questa azienda

        # Già processato?
        if mail_file["id"] in processed:
            skip_already += 1
            print(f"  ↷ {nome_azienda} — mail già processata, skip")
            continue

        print(f"\n  → {nome_azienda}")
        print(f"    TXT trovato: {mail_file['name']}")

        # Cerca PDF media kit
        pdf_file = find_mediakit_pdf(files, nome_azienda)
        if not pdf_file:
            skip_no_pdf += 1
            print(f"    ⚠️  PDF media kit non trovato — skip (aggiornato Supabase)")
            upsert_company_a7(supabase, nome_azienda,
                              mail_file["id"], "", "skipped_no_pdf")
            continue

        print(f"    PDF trovato: {pdf_file['name']}")

        # Scarica TXT e parsa
        try:
            txt_content = download_txt_content(drive, mail_file["id"])
            mail_data   = parse_mail_txt(txt_content)
        except Exception as e:
            print(f"    ERRORE lettura TXT: {e}")
            upsert_company_a7(supabase, nome_azienda, mail_file["id"], "", "error_read_txt")
            continue

        if not mail_data["destinatario"] or not mail_data["oggetto"]:
            print(f"    ERRORE: TXT malformato (destinatario o oggetto mancante)")
            print(f"    Contenuto TXT: {txt_content[:200]}")
            upsert_company_a7(supabase, nome_azienda, mail_file["id"], "", "error_malformed_txt")
            continue

        # Scarica PDF
        try:
            pdf_bytes = download_pdf_bytes(drive, pdf_file["id"])
        except Exception as e:
            print(f"    ERRORE download PDF: {e}")
            upsert_company_a7(supabase, nome_azienda, mail_file["id"], "", "error_read_pdf")
            continue

        # Crea bozza Gmail
        try:
            draft_id = create_gmail_draft(
                gmail, mail_data,
                pdf_bytes, pdf_file["name"],
                nome_azienda
            )
        except Exception as e:
            print(f"    ERRORE Gmail: {e}")
            upsert_company_a7(supabase, nome_azienda, mail_file["id"], "", "error_gmail")
            continue

        # Aggiorna Supabase
        upsert_company_a7(supabase, nome_azienda,
                          mail_file["id"], draft_id, "draft_created")

        # Push notification
        send_push(nome_azienda, draft_id)

        bozze_create += 1

    # ─── Riepilogo ────────────────────────────────────────────────────────────
    print(f"\n✅ A7 completato")
    print(f"   Bozze create:      {bozze_create}")
    print(f"   Skip (già fatto):  {skip_already}")
    print(f"   Skip (no PDF):     {skip_no_pdf}")


if __name__ == "__main__":
    main()
