"""
GDC IA TEAM — Script A1 Monthly
Ogni 1° del mese alle 08:00 ora italiana.

Flusso:
1. Instagram Graph API → metriche post + reel + stories del mese precedente
2. Compila Instagram_Analytics_GDC.xlsx (5 sheet)
3. Carica su Google Drive (cartella A1.2)
4. Aggiorna Supabase → stato A1 = done
5. Invia Web Push notification

Secrets GitHub richiesti:
  IG_ACCESS_TOKEN       — token a lunga durata Instagram Graph API
  IG_USER_ID            — ID numerico account Instagram
  GOOGLE_CREDENTIALS    — JSON service account Google (base64)
  DRIVE_FOLDER_A1       — ID cartella Drive A1.2
  SUPABASE_URL          — URL progetto Supabase
  SUPABASE_KEY          — anon/service key Supabase
  PUSH_SUBSCRIPTION     — JSON subscription Web Push (base64)
  VAPID_PRIVATE_KEY     — chiave privata VAPID
  VAPID_EMAIL           — email per VAPID
"""

import os
import json
import base64
import tempfile
import requests
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from calendar import monthrange

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter

from supabase import create_client
from pywebpush import webpush, WebPushException


# ─── CONFIG ────────────────────────────────────────────────────────────────────

IG_TOKEN     = os.environ["IG_ACCESS_TOKEN"]
IG_USER_ID   = os.environ["IG_USER_ID"]
DRIVE_FOLDER = os.environ["DRIVE_FOLDER_A1"]
SUPA_URL     = os.environ["SUPABASE_URL"]
SUPA_KEY     = os.environ["SUPABASE_KEY"]
VAPID_PRIV   = os.environ["VAPID_PRIVATE_KEY"]
VAPID_EMAIL  = os.environ["VAPID_EMAIL"]

EXCEL_FILENAME       = "Instagram_Analytics_GDC"        # nome senza estensione — file nativo Google
EXCEL_FILENAME_LOCAL = "Instagram_Analytics_GDC.xlsx"    # nome locale temporaneo con estensione

# Mese precedente (quello da analizzare)
today        = date.today()
target       = today - relativedelta(months=1)
MESE_NUM     = target.month
ANNO         = target.year
MESE_IT      = [
    "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"
][MESE_NUM]
MESE_LABEL   = f"{MESE_IT} {ANNO}"
PRIMO_GIORNO = date(ANNO, MESE_NUM, 1)
ULTIMO_GIORNO = date(ANNO, MESE_NUM, monthrange(ANNO, MESE_NUM)[1])

# Palette colori GDC
COLOR_GRAY_SEP  = "D3D3D3"   # separatore mesi
COLOR_YELLOW    = "FFD700"   # categorie da confermare
COLOR_HEADER    = "1C1C1C"   # header nero
COLOR_WHITE     = "FFFFFF"

print(f"▶ A1 Monthly — {MESE_LABEL}")
print(f"  Periodo: {PRIMO_GIORNO} → {ULTIMO_GIORNO}")


# ─── 1. INSTAGRAM GRAPH API ─────────────────────────────────────────────────────

def ig_get(endpoint, params={}):
    """Chiamata GET all'API Instagram Graph."""
    base = f"https://graph.facebook.com/v21.0/{endpoint}"
    params["access_token"] = IG_TOKEN
    r = requests.get(base, params=params)
    r.raise_for_status()
    return r.json()


def fetch_post_insights(media_id, media_type):
    """
    Recupera metriche avanzate per un singolo post/reel via /insights.
    Le metriche disponibili variano per tipo di media.
    """
    # Metriche per IMAGE/CAROUSEL_ALBUM
    if media_type in ("IMAGE", "CAROUSEL_ALBUM"):
        metric = "impressions,reach,saved,shares,likes,comments,follows"
    # Metriche per VIDEO/REELS
    elif media_type in ("VIDEO", "REELS"):
        metric = "impressions,reach,saved,shares,likes,comments,follows,plays"
    else:
        metric = "impressions,reach,saved,shares,likes,comments,follows"

    try:
        ins = ig_get(f"{media_id}/insights", {
            "metric": metric,
            "period": "lifetime"
        })
        return {m["name"]: m["values"][0]["value"] for m in ins.get("data", [])}
    except Exception as e:
        # Prova con metriche minime se quelle avanzate falliscono
        try:
            ins = ig_get(f"{media_id}/insights", {
                "metric": "impressions,reach,saved,shares",
                "period": "lifetime"
            })
            return {m["name"]: m["values"][0]["value"] for m in ins.get("data", [])}
        except Exception:
            return {}


def fetch_posts():
    """
    Recupera tutti i post/reel del mese target.
    Paginazione automatica finché non usciamo dal periodo.
    """
    print("  → Fetch post/reel...")
    # Solo campi base nel media endpoint — le metriche si prendono da /insights
    fields = "id,timestamp,media_type,caption,permalink,like_count,comments_count,username"
    posts = []
    url = f"{IG_USER_ID}/media"
    params = {"fields": fields, "limit": 100}

    while True:
        data = ig_get(url, params)
        items = data.get("data", [])

        for item in items:
            ts = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
            item_date = ts.date()

            if item_date > ULTIMO_GIORNO:
                continue  # ancora nel mese corrente, salta
            if item_date < PRIMO_GIORNO:
                print(f"    Trovati {len(posts)} post nel periodo")
                return posts

            # Recupera metriche avanzate per ogni media
            metrics = fetch_post_insights(item["id"], item.get("media_type", "IMAGE"))
            item.update(metrics)
            posts.append(item)

        # Paginazione
        next_url = data.get("paging", {}).get("next")
        if not next_url:
            break
        import urllib.parse as urlparse
        parsed = urlparse.urlparse(next_url)
        params = dict(urlparse.parse_qsl(parsed.query))
        url = f"{IG_USER_ID}/media"

    print(f"    Trovati {len(posts)} post nel periodo")
    return posts


def fetch_stories_archive():
    """
    Recupera stories dal Drive (accumulo giornaliero dello script daily).
    Restituisce le top 10 per visualizzazioni del mese target.
    """
    print("  → Carico stories da Drive archive...")
    # Le stories sono già salvate dallo script daily in JSON su Drive
    # Vengono caricate nella funzione drive_download_stories()
    return []  # placeholder — popolato dopo il download Drive


# ─── 2. GOOGLE DRIVE ────────────────────────────────────────────────────────────

def get_drive_service():
    """Crea servizio Google Drive da credenziali service account."""
    creds_b64 = os.environ["GOOGLE_CREDENTIALS"]
    creds_json = json.loads(base64.b64decode(creds_b64))
    scopes = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets"
    ]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    return build("drive", "v3", credentials=creds), creds


def drive_find_file(service, name, folder_id):
    """
    Trova un file per nome in una cartella Drive.
    Ritorna (id, mimeType) o (None, None).
    """
    query = f"name='{name}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name, mimeType)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"], files[0]["mimeType"]

    name_no_ext = name.rsplit(".", 1)[0] if "." in name else None
    if name_no_ext and name_no_ext != name:
        query2 = f"name='{name_no_ext}' and '{folder_id}' in parents and trashed=false"
        results2 = service.files().list(q=query2, fields="files(id, name, mimeType)").execute()
        files2 = results2.get("files", [])
        if files2:
            return files2[0]["id"], files2[0]["mimeType"]

    return None, None


def drive_download_excel(service, file_id, mime_type, dest_path):
    """
    Scarica il file Excel dal Drive.
    Se e un Foglio Google nativo, usa Export in formato xlsx.
    """
    from googleapiclient.http import MediaIoBaseDownload
    import io

    GOOGLE_SHEETS_MIME = "application/vnd.google-apps.spreadsheet"
    XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    if mime_type == GOOGLE_SHEETS_MIME:
        request = service.files().export_media(fileId=file_id, mimeType=XLSX_MIME)
        print(f"    Export Foglio Google → xlsx")
    else:
        request = service.files().get_media(fileId=file_id)

    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    with open(dest_path, "wb") as f:
        f.write(fh.read())
    print(f"    Excel scaricato: {dest_path}")


def drive_download_stories_json(service, folder_id):
    """
    Scarica tutti i file stories_[mese]_[anno].json del mese target.
    Restituisce lista di stories aggregate.
    """
    filename = f"stories_{MESE_IT.lower()}_{ANNO}.json"
    file_id, _ = drive_find_file(service, filename, folder_id)
    if not file_id:
        print(f"    Nessun file stories trovato: {filename}")
        return []

    from googleapiclient.http import MediaIoBaseDownload
    import io
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    data = json.loads(fh.read())
    print(f"    Caricate {len(data)} stories dall'archivio")
    return data


def drive_upload_excel(service, local_path, folder_id, existing_id=None):
    """
    Carica (o aggiorna) il file Excel su Drive convertendolo in Foglio Google nativo.
    La conversione avviene passando mimeType nativo nel file_metadata.
    I file nativi Google sono leggibili direttamente dagli agenti successivi via Drive API.
    """
    media = MediaFileUpload(
        local_path,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    if existing_id:
        # Aggiorna file esistente — Drive mantiene il formato nativo
        service.files().update(fileId=existing_id, media_body=media).execute()
        print(f"    Foglio Google aggiornato su Drive (ID: {existing_id})")
    else:
        # Crea nuovo file con conversione automatica in Foglio Google nativo
        meta = {
            "name": EXCEL_FILENAME,          # senza estensione
            "parents": [folder_id],
            "mimeType": "application/vnd.google-apps.spreadsheet"  # forza conversione
        }
        f = service.files().create(body=meta, media_body=media, fields="id").execute()
        print(f"    Foglio Google creato su Drive (ID: {f['id']})")


# ─── 3. EXCEL — STRUTTURA E COMPILAZIONE ────────────────────────────────────────

SHEET_NAMES = [
    "Panoramica Profilo",
    "Insights Post",
    "Insights Stories",
    "KPI Medi",
    "Note Strategiche"
]

HEADERS = {
    "Panoramica Profilo": [
        "Mese", "Data Run", "Periodo",
        "Post Totali Profilo", "Follower Totali", "Following",
        "Visualizzazioni Totali", "Interazioni Totali",
        "N° Post/Reel Pubblicati", "N° Stories Pubblicate", "Note"
    ],
    "Insights Post": [
        "Mese", "Data", "Ora", "Tipo Contenuto", "Tipo Autore",
        "Caption", "Categoria Primaria", "Categoria Secondaria",
        "Permalink", "Visualizzazioni", "Reach", "Like", "Commenti",
        "Salvataggi", "Condivisioni", "Interazioni Totali",
        "Engagement Rate", "Tasso Viralità", "Sentiment Score",
        "Follower Acquisiti", "Collaborazione Sì/No", "Note"
    ],
    "Insights Stories": [
        "Mese", "Data", "Ora", "Permalink",
        "Visualizzazioni", "Reach", "Like", "Condivisioni",
        "Risposte", "Navigation Totale", "Sticker Taps",
        "Visite Profilo", "Follower Acquisiti", "Note"
    ],
    "KPI Medi": [
        "Mese", "ER Medio", "Viz Medie Post", "Reach Medio Post",
        "Like Medio", "Commenti Medi", "Salvataggi Medi",
        "Tasso Viralità Medio", "Sentiment Score Medio",
        "Viz Medie Stories", "Reach Medio Stories"
    ]
}


def safe_mean(values):
    """Media ignorando None e 0."""
    valid = [v for v in values if v is not None and v != ""]
    return round(sum(valid) / len(valid), 4) if valid else ""


def media_type_to_gdc(media_type):
    mapping = {"VIDEO": "Reel", "CAROUSEL_ALBUM": "Carosello", "IMAGE": "Post"}
    return mapping.get(media_type, media_type)


def parse_ts(ts_str):
    """Parsing timestamp ISO → (date_str GG/MM/AAAA, ora_str HH:MM)."""
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    return dt.strftime("%d/%m/%Y"), dt.strftime("%H:%M")


def get_or_create_workbook(local_path):
    """Apre l'Excel esistente o ne crea uno nuovo con i 5 sheet."""
    if os.path.exists(local_path):
        wb = openpyxl.load_workbook(local_path)
        # Assicura che tutti gli sheet esistano
        for name in SHEET_NAMES:
            if name not in wb.sheetnames:
                wb.create_sheet(name)
        print("    Workbook esistente caricato")
    else:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for name in SHEET_NAMES:
            wb.create_sheet(name)
        # Scrivi gli header
        for sheet_name, headers in HEADERS.items():
            ws = wb[sheet_name]
            ws.append(headers)
            _style_header_row(ws, headers)
        print("    Nuovo workbook creato")
    return wb


def _style_header_row(ws, headers):
    """Stile header: sfondo nero, testo bianco, bold."""
    header_fill = PatternFill("solid", fgColor=COLOR_HEADER)
    white_font  = Font(color=COLOR_WHITE, bold=True)
    for col, _ in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = header_fill
        cell.font = white_font
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(col)].width = 18


def _add_separator_row(ws, n_cols):
    """Riga grigia separatore tra mesi."""
    ws.append([""] * n_cols)
    gray_fill = PatternFill("solid", fgColor=COLOR_GRAY_SEP)
    row = ws.max_row
    for col in range(1, n_cols + 1):
        ws.cell(row=row, column=col).fill = gray_fill


def find_insert_row(ws, mese_label):
    """
    Trova la riga di inserimento: sopra i dati del mese più recente già presente.
    Struttura: header (row 1) → mese più recente → separatore → mese precedente → ...
    Se il mese esiste già, ritorna None (skip).
    """
    # Controlla se il mese esiste già
    for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
        if row[0] == mese_label:
            return None  # già presente

    # Inserisci dopo l'header (row 1) — i nuovi dati vanno sempre in cima
    return 2


def compile_sheet_post(wb, posts):
    """Compila Sheet 2 — Insights Post."""
    ws = wb["Insights Post"]
    headers = HEADERS["Insights Post"]

    # Controlla se il mese esiste già
    for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
        if row[0] == MESE_LABEL:
            print(f"    Sheet Post: {MESE_LABEL} già presente, skip")
            return

    # Ordina per data decrescente
    posts_sorted = sorted(
        posts,
        key=lambda p: p.get("timestamp", ""),
        reverse=True
    )

    # Trova riga di inserimento (dopo header, prima degli altri mesi)
    insert_at = 2

    rows_to_insert = []
    yellow_fill = PatternFill("solid", fgColor=COLOR_YELLOW)

    for p in posts_sorted:
        data_str, ora_str = parse_ts(p.get("timestamp", ""))
        tipo_contenuto = media_type_to_gdc(p.get("media_type", ""))
        username       = p.get("username", p.get("owner", {}).get("username", ""))
        tipo_autore    = "ORIGINALE" if username == "giandcdalcorso" else "REPOST"

        views     = p.get("impressions", p.get("views", 0)) or 0
        reach     = p.get("reach") if tipo_autore == "ORIGINALE" else None
        likes     = p.get("like_count", 0) or 0
        comments  = p.get("comments_count", 0) or 0
        saved     = p.get("saved", 0) or 0
        shares    = p.get("shares", 0) or 0
        follows   = p.get("follows", 0) or 0

        interactions = likes + comments + saved + shares
        er           = round(interactions / reach, 4) if reach else ""
        viralita     = round((shares / reach) * 100, 4) if reach else ""
        sentiment    = round((saved + shares) / likes, 4) if likes > 0 else ""
        collaborazione = "Sì" if tipo_autore == "REPOST" else "No"

        rows_to_insert.append([
            MESE_LABEL, data_str, ora_str, tipo_contenuto, tipo_autore,
            p.get("caption", "")[:500] if p.get("caption") else "",
            "",  # Categoria Primaria — da confermare
            "",  # Categoria Secondaria — da confermare
            p.get("permalink", ""),
            views, reach if reach is not None else "",
            likes, comments, saved, shares,
            interactions, er, viralita, sentiment,
            follows, collaborazione, ""
        ])

    # Inserisci separatore + righe (dal basso verso l'alto per mantenere l'ordine)
    # Prima il separatore, poi le righe dati
    sep_row = [""] * len(headers)
    ws.insert_rows(insert_at, amount=len(rows_to_insert) + 1)

    for i, row_data in enumerate(rows_to_insert):
        r = insert_at + i
        for j, val in enumerate(row_data, 1):
            cell = ws.cell(row=r, column=j, value=val)
            # Celle gialle per categorie ORIGINALE
            if j in (7, 8) and row_data[4] == "ORIGINALE":
                cell.fill = yellow_fill

    # Riga separatore grigia dopo i dati del nuovo mese
    gray_fill = PatternFill("solid", fgColor=COLOR_GRAY_SEP)
    sep_row_num = insert_at + len(rows_to_insert)
    for col in range(1, len(headers) + 1):
        ws.cell(row=sep_row_num, column=col).fill = gray_fill

    print(f"    Sheet Post: {len(rows_to_insert)} righe inserite")
    return rows_to_insert


def compile_sheet_stories(wb, stories):
    """Compila Sheet 3 — Insights Stories (top 10 per visualizzazioni)."""
    ws = wb["Insights Stories"]
    headers = HEADERS["Insights Stories"]

    for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
        if row[0] == MESE_LABEL:
            print(f"    Sheet Stories: {MESE_LABEL} già presente, skip")
            return

    # Top 10 per visualizzazioni
    top10 = sorted(stories, key=lambda s: s.get("impressions", 0), reverse=True)[:10]

    insert_at = 2
    ws.insert_rows(insert_at, amount=len(top10) + 1)

    for i, s in enumerate(top10):
        data_str, ora_str = parse_ts(s.get("timestamp", ""))
        r = insert_at + i
        ws.cell(row=r, column=1, value=MESE_LABEL)
        ws.cell(row=r, column=2, value=data_str)
        ws.cell(row=r, column=3, value=ora_str)
        ws.cell(row=r, column=4, value=s.get("permalink", ""))
        ws.cell(row=r, column=5, value=s.get("impressions", 0))
        ws.cell(row=r, column=6, value=s.get("reach", ""))
        ws.cell(row=r, column=7, value=s.get("like_count", 0))
        ws.cell(row=r, column=8, value=s.get("shares", 0))
        ws.cell(row=r, column=9, value=s.get("replies", 0))
        ws.cell(row=r, column=10, value=s.get("navigation", 0))
        ws.cell(row=r, column=11, value=s.get("taps_forward", 0))
        ws.cell(row=r, column=12, value=s.get("profile_visits", 0))
        ws.cell(row=r, column=13, value=s.get("follows", 0))
        ws.cell(row=r, column=14, value="")

    # Separatore
    gray_fill = PatternFill("solid", fgColor=COLOR_GRAY_SEP)
    sep_row = insert_at + len(top10)
    for col in range(1, len(headers) + 1):
        ws.cell(row=sep_row, column=col).fill = gray_fill

    print(f"    Sheet Stories: {len(top10)} righe inserite")
    return top10


def compile_sheet_panoramica(wb, posts, stories):
    """Compila Sheet 1 — Panoramica Profilo."""
    ws = wb["Panoramica Profilo"]

    for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
        if row[0] == MESE_LABEL:
            print(f"    Sheet Panoramica: {MESE_LABEL} già presente, skip")
            return

    originali = [p for p in posts if p.get("username", "") == "giandcdalcorso"]
    tot_views_post = sum(p.get("impressions", 0) or 0 for p in posts)
    tot_views_stories = sum(s.get("impressions", 0) or 0 for s in stories)
    tot_interactions = sum(
        (p.get("like_count", 0) or 0) +
        (p.get("comments_count", 0) or 0) +
        (p.get("saved", 0) or 0) +
        (p.get("shares", 0) or 0)
        for p in posts
    )
    periodo = f"{PRIMO_GIORNO.strftime('%d/%m/%Y')} → {ULTIMO_GIORNO.strftime('%d/%m/%Y')}"

    row_data = [
        MESE_LABEL,
        date.today().strftime("%d/%m/%Y"),
        periodo,
        "",  # Post Totali Profilo — non disponibile via API senza permessi extra
        "",  # Follower Totali — idem
        "",  # Following — idem
        tot_views_post + tot_views_stories,
        tot_interactions,
        len(originali),
        len(stories),
        ""
    ]

    ws.insert_rows(2, amount=1)
    for j, val in enumerate(row_data, 1):
        ws.cell(row=2, column=j, value=val)

    print(f"    Sheet Panoramica: riga {MESE_LABEL} inserita")


def compile_sheet_kpi(wb, posts, stories):
    """Compila Sheet 4 — KPI Medi."""
    ws = wb["KPI Medi"]

    for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
        if row[0] == MESE_LABEL:
            print(f"    Sheet KPI: {MESE_LABEL} già presente, skip")
            return

    originali = [p for p in posts if p.get("username", "") == "giandcdalcorso"]
    con_reach  = [p for p in originali if p.get("reach")]

    er_vals       = []
    viralita_vals = []
    for p in con_reach:
        r = p["reach"]
        i = (p.get("like_count", 0) or 0) + (p.get("comments_count", 0) or 0) + \
            (p.get("saved", 0) or 0) + (p.get("shares", 0) or 0)
        s = p.get("shares", 0) or 0
        er_vals.append(round(i / r, 4) if r else None)
        viralita_vals.append(round((s / r) * 100, 4) if r else None)

    sentiment_vals = []
    for p in originali:
        likes = p.get("like_count", 0) or 0
        saved = p.get("saved", 0) or 0
        shares = p.get("shares", 0) or 0
        if likes > 0:
            sentiment_vals.append(round((saved + shares) / likes, 4))

    row_data = [
        MESE_LABEL,
        safe_mean(er_vals),
        safe_mean([p.get("impressions", 0) for p in originali]),
        safe_mean([p.get("reach") for p in con_reach]),
        safe_mean([p.get("like_count", 0) for p in originali]),
        safe_mean([p.get("comments_count", 0) for p in originali]),
        safe_mean([p.get("saved", 0) for p in originali]),
        safe_mean(viralita_vals),
        safe_mean(sentiment_vals),
        safe_mean([s.get("impressions", 0) for s in stories]),
        safe_mean([s.get("reach", 0) for s in stories]),
    ]

    ws.insert_rows(2, amount=1)
    for j, val in enumerate(row_data, 1):
        ws.cell(row=2, column=j, value=val)

    print(f"    Sheet KPI: riga {MESE_LABEL} inserita")


# ─── 4. SUPABASE ─────────────────────────────────────────────────────────────────

def supabase_update_state(agent_id, stato, extra={}):
    """Aggiorna lo stato di un agente nella tabella agent_states."""
    supabase = create_client(SUPA_URL, SUPA_KEY)
    data = {
        "agent_id": agent_id,
        "stato": stato,
        "updated_at": datetime.utcnow().isoformat(),
        **extra
    }
    supabase.table("agent_states").upsert(data, on_conflict="agent_id").execute()
    print(f"    Supabase: {agent_id} → {stato}")


# ─── 5. WEB PUSH ─────────────────────────────────────────────────────────────────

def send_push(title, body):
    """Invia Web Push notification via VAPID."""
    sub_b64 = os.environ.get("PUSH_SUBSCRIPTION", "")
    if not sub_b64:
        print("    Push: nessuna subscription configurata, skip")
        return
    try:
        subscription = json.loads(base64.b64decode(sub_b64))
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=VAPID_PRIV,
            vapid_claims={"sub": f"mailto:{VAPID_EMAIL}"}
        )
        print(f"    Push inviata: {title}")
    except WebPushException as e:
        print(f"    Push ERRORE: {e}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────────

def main():
    # Aggiorna stato → working
    supabase_update_state("a1", "working")

    # 1. Fetch dati Instagram
    posts = fetch_posts()

    # 2. Setup Drive
    drive_service, _ = get_drive_service()

    # 3. Carica stories archiviate dallo script daily
    stories = drive_download_stories_json(drive_service, DRIVE_FOLDER)

    # 4. Scarica Excel esistente (o parti da zero)
    with tempfile.TemporaryDirectory() as tmpdir:
        local_excel = os.path.join(tmpdir, EXCEL_FILENAME_LOCAL)

        existing_id, existing_mime = drive_find_file(drive_service, EXCEL_FILENAME_LOCAL, DRIVE_FOLDER)
        if existing_id:
            drive_download_excel(drive_service, existing_id, existing_mime, local_excel)

        wb = get_or_create_workbook(local_excel)

        # 5. Compila i 4 sheet (il 5° è di A2/A3, non si tocca)
        post_rows = compile_sheet_post(wb, posts)
        compile_sheet_stories(wb, stories)
        compile_sheet_panoramica(wb, posts, stories)
        compile_sheet_kpi(wb, posts, stories)

        # 6. Salva e carica su Drive
        wb.save(local_excel)
        drive_upload_excel(drive_service, local_excel, DRIVE_FOLDER, existing_id)
    # 7. Aggiorna Supabase → done
    supabase_update_state("a1", "done", {
        "mese": MESE_LABEL,
        "n_post": len(posts),
        "n_stories": len(stories),
        "drive_folder": DRIVE_FOLDER
    })

    # 8. Push notification → sblocca A2
    supabase_update_state("a2", "ready")
    send_push(
        "✅ A1 completato",
        f"Analytics {MESE_LABEL} pronti. Apri A2 per generare il report."
    )

    originali = len([p for p in posts if p.get("username", "") == "giandcdalcorso"])
    repost    = len(posts) - originali
    print(f"\n✅ A1 Monthly completato — {MESE_LABEL}")
    print(f"   Post: {len(posts)} (ORIGINALE: {originali} | REPOST: {repost})")
    print(f"   Stories in archivio: {len(stories)}")


if __name__ == "__main__":
    main()
