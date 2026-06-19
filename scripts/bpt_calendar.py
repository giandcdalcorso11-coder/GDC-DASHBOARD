"""
GDC IA TEAM — Script BPT Calendar
Gira il 1° del mese alle 08:00 in parallelo ad A1.

Flusso:
1. Playwright apre il sito BPT e carica la lista tornei 2026
2. Per ogni torneo nel mese da pianificare (mese corrente + 1):
   → Entra nella pagina del torneo
   → Cerca "Dal Corso" tra i partecipanti
   → Se trovato → calcola partenza/rientro/riposo
3. Genera testo calendario formattato per A3
4. Salva bpt_[mese]_[anno].txt su Drive (cartella A3)
5. Aggiorna Supabase → calendario_bpt in agent_states

Secrets GitHub richiesti:
  GOOGLE_CREDENTIALS  — JSON service account Google (base64)
  DRIVE_FOLDER_A3     — ID cartella Drive A3
  SUPABASE_URL        — URL progetto Supabase
  SUPABASE_KEY        — anon/service key Supabase
"""

import os
import json
import base64
import re
import tempfile
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from supabase import create_client


# ─── CONFIG ────────────────────────────────────────────────────────────────────

DRIVE_FOLDER_A3 = os.environ.get("DRIVE_FOLDER_A3", "")  # opzionale
SUPA_URL        = os.environ["SUPABASE_URL"]
SUPA_KEY        = os.environ["SUPABASE_KEY"]

# Mese da pianificare = mese corrente + 1
today           = date.today()
target          = today + relativedelta(months=1)
MESE_NUM        = target.month
ANNO            = target.year
MESI_IT         = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
                   "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]
MESE_IT         = MESI_IT[MESE_NUM]
MESE_LABEL      = f"{MESE_IT} {ANNO}"
MESE_IT_LOWER   = MESE_IT.lower()

BPT_URL         = f"https://en.volleyballworld.com/beachvolleyball/competitions/beach-pro-tour/{ANNO}/"
PLAYER_SEARCH_TERMS = ["dal corso", "cottafava", "cottafava/dal corso"]  # tutti i modi in cui può apparire

print(f"▶ BPT Calendar — mese da pianificare: {MESE_LABEL}")


# ─── LISTA PAESI OLTREOCEANO ────────────────────────────────────────────────────

# Città/paesi che richiedono +6 giorni di anticipo
OLTREOCEANO_KEYWORDS = [
    # Americhe
    "brazil", "brasil", "usa", "united states", "canada", "mexico", "méxico",
    "argentina", "chile", "colombia", "peru", "uruguay", "brazil",
    "rio", "sao paulo", "são paulo", "toronto", "chicago", "las vegas",
    "long beach", "hermosa beach", "cancun", "cancún",
    # Asia
    "china", "japan", "korea", "thailand", "vietnam", "indonesia", "malaysia",
    "singapore", "philippines", "taiwan", "hong kong", "beijing", "shanghai",
    "tokyo", "osaka", "bangkok", "kuala lumpur",
    # Oceania
    "australia", "new zealand", "sydney", "melbourne", "auckland",
    # Medio Oriente lontano (opzionale — puoi rimuovere se preferisci +4)
    "qatar", "dubai", "abu dhabi", "doha",
]


def is_oltreoceano(location: str) -> bool:
    """True se la destinazione richiede +6 giorni di anticipo."""
    loc = location.lower()
    return any(kw in loc for kw in OLTREOCEANO_KEYWORDS)


# ─── PLAYWRIGHT — SCRAPING BPT ──────────────────────────────────────────────────

API_URL = f"https://en.volleyballworld.com/api/v1/globalschedule/bpt/competitions/{ANNO}/"

# Categorie da escludere (Futures = tornei minori)
SKIP_CATEGORIES = ["futures", "future"]

def scrape_bpt_tournaments(page) -> list[dict]:
    """
    Chiama direttamente l'API JSON di volleyballworld tramite Playwright.
    Più affidabile dello scraping HTML — restituisce dati strutturati.
    Esclude i tornei Futures (troppo numerosi e non rilevanti).
    """
    print(f"  → Chiamo API BPT: {API_URL}")

    # Usa Playwright per fare la chiamata API (bypassa robots.txt)
    response = page.request.get(API_URL, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://en.volleyballworld.com/"
    })

    if not response.ok:
        print(f"    ERRORE API: {response.status}")
        return []

    data = response.json()
    print(f"    API risposta ricevuta — parsing tornei...")

    tournaments = []
    # La risposta può essere lista diretta o nested
    items = data if isinstance(data, list) else data.get("competitions", data.get("events", data.get("results", [])))

    for item in items:
        # Estrai nome/titolo
        nome = (item.get("title") or item.get("name") or
                item.get("competition_name") or item.get("event_name") or "")

        # Salta i Futures
        nome_lower = nome.lower()
        if any(skip in nome_lower for skip in SKIP_CATEGORIES):
            print(f"    Skip Futures: {nome}")
            continue

        # Estrai location
        location = (item.get("location") or item.get("city") or
                   item.get("venue") or item.get("country") or "")
        if isinstance(location, dict):
            location = location.get("city", "") or location.get("name", "")

        # Estrai date
        date_start_str = (item.get("start_date") or item.get("date_start") or
                         item.get("startDate") or item.get("start") or "")
        date_end_str   = (item.get("end_date") or item.get("date_end") or
                         item.get("endDate") or item.get("end") or "")

        d_start = parse_api_date(date_start_str)
        d_end   = parse_api_date(date_end_str)

        # URL pagina torneo
        slug = (item.get("slug") or item.get("url_slug") or
               item.get("id") or nome.lower().replace(" ", "-"))
        url = (item.get("url") or item.get("link") or
               f"https://en.volleyballworld.com/beachvolleyball/competitions/beach-pro-tour/events/{slug}/")

        # Cerca presenza giocatore nella lista teams/players se disponibile
        teams    = item.get("teams", item.get("players", item.get("athletes", [])))
        teams_str = json.dumps(teams).lower() if teams else ""
        found_in_api = any(term in teams_str for term in PLAYER_SEARCH_TERMS)

        tournaments.append({
            "nome":             nome,
            "slug":             str(slug),
            "url":              url,
            "date_start":       d_start,
            "date_end":         d_end,
            "location":         location,
            "gianluca_presente": found_in_api,
            "raw":              item  # mantieni raw per debug
        })

    print(f"    Tornei parsati (esclusi Futures): {len(tournaments)}")
    return tournaments


def parse_api_date(date_str) -> date:
    """Converte stringa data API in oggetto date. Gestisce stringhe e timestamp."""
    if not date_str:
        return None
    from datetime import datetime

    # Se è già un oggetto date
    if isinstance(date_str, date):
        return date_str

    # Converti in stringa se necessario
    date_str = str(date_str).strip()

    # Prova vari formati — dal più comune al meno comune
    formats = [
        "%Y-%m-%d",           # 2026-07-01
        "%Y-%m-%dT%H:%M:%S",  # 2026-07-01T00:00:00
        "%Y-%m-%dT%H:%M:%SZ", # 2026-07-01T00:00:00Z
        "%Y-%m-%dT%H:%M:%S.%f", # con millisecondi
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y%m%d",
        "%d-%m-%Y",
        "%B %d, %Y",          # July 1, 2026
        "%d %B %Y",           # 1 July 2026
    ]

    # Prima prova i primi 10 caratteri (data senza ora)
    for fmt in formats:
        try:
            # Prova stringa completa
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
        try:
            # Prova solo i primi 10 caratteri
            return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except ValueError:
            pass

    print(f"      ATTENZIONE: formato data non riconosciuto: '{date_str}'")
    return None


def scrape_tournament_details(page, tournament: dict) -> dict:
    """
    Entra nella pagina del singolo torneo e recupera:
    - date precise
    - location
    - se "Dal Corso" è nella lista partecipanti
    """
    url = tournament["url"]
    print(f"    Analizzo: {url}")

    # Assicura URL assoluto
    base_url = url
    if base_url.startswith("/"):
        base_url = "https://en.volleyballworld.com" + base_url
    elif not base_url.startswith("http"):
        base_url = "https://en.volleyballworld.com/" + base_url

    # Vai direttamente alla pagina squadre maschili (dove appare "Cottafava/Dal Corso")
    teams_url = base_url.rstrip("/") + "/teams/men/by-country/"

    for check_url in [teams_url, base_url]:
        try:
            page.goto(check_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)  # pausa anti-rate-limit
        except PlaywrightTimeout:
            print(f"      Timeout su {check_url}, skip")
            page.wait_for_timeout(5000)  # pausa extra dopo timeout
            continue

        # Aspetta rendering JS lista squadre
        try:
            page.wait_for_selector("table, [class*='team'], [class*='player']", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(2000)

        full_text = page.inner_text("body").lower()
        found = any(term in full_text for term in PLAYER_SEARCH_TERMS)

        if found:
            matched = [t for t in PLAYER_SEARCH_TERMS if t in full_text]
            print(f"      ✅ Trovato {matched} su {check_url}")
            tournament["gianluca_presente"] = True
            break
    else:
        tournament["gianluca_presente"] = False

    # Estrai date — formato tipico: "15 - 20 Jul 2026" o "Jul 15-20, 2026"
    tournament["date_start"], tournament["date_end"] = extract_dates_from_page(page, full_text)

    # Estrai location
    tournament["location"] = extract_location_from_page(page, full_text, tournament["slug"])

    return tournament


def extract_dates_from_page(page, full_text: str):
    """
    Tenta di estrarre date start/end dalla pagina del torneo.
    Restituisce (date_start, date_end) o (None, None).
    """
    import re
    from datetime import datetime

    MESI_EN = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10,
        "november": 11, "december": 12
    }

    # Pattern: "15 - 20 Jul 2026" o "15-20 Jul 2026"
    pattern1 = r'(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([a-z]{3,9})\s+(\d{4})'
    m = re.search(pattern1, full_text)
    if m:
        d_start, d_end, month_str, year = m.groups()
        month = MESI_EN.get(month_str[:3].lower())
        if month:
            try:
                return (
                    date(int(year), month, int(d_start)),
                    date(int(year), month, int(d_end))
                )
            except ValueError:
                pass

    # Pattern: "Jul 15 - 20, 2026"
    pattern2 = r'([a-z]{3,9})\s+(\d{1,2})\s*[-–]\s*(\d{1,2}),?\s*(\d{4})'
    m = re.search(pattern2, full_text)
    if m:
        month_str, d_start, d_end, year = m.groups()
        month = MESI_EN.get(month_str[:3].lower())
        if month:
            try:
                return (
                    date(int(year), month, int(d_start)),
                    date(int(year), month, int(d_end))
                )
            except ValueError:
                pass

    # Pattern: "15 Jul - 20 Jul 2026"
    pattern3 = r'(\d{1,2})\s+([a-z]{3,9})\s*[-–]\s*(\d{1,2})\s+([a-z]{3,9})\s+(\d{4})'
    m = re.search(pattern3, full_text)
    if m:
        d_start, m_start, d_end, m_end, year = m.groups()
        month_s = MESI_EN.get(m_start[:3].lower())
        month_e = MESI_EN.get(m_end[:3].lower())
        if month_s and month_e:
            try:
                return (
                    date(int(year), month_s, int(d_start)),
                    date(int(year), month_e, int(d_end))
                )
            except ValueError:
                pass

    return None, None


def extract_location_from_page(page, full_text: str, slug: str) -> str:
    """
    Estrae la location del torneo.
    Prima prova elementi specifici, poi legge dallo slug URL.
    """
    # Prova a trovare la città in elementi h1/h2/title
    location_el = page.query_selector("h1, h2, [class*='location'], [class*='city']")
    if location_el:
        text = location_el.inner_text().strip()
        if len(text) < 60:
            return text

    # Estrai dalla slug URL: "bpt-elite16-hamburg-2026" → "Hamburg"
    # Rimuovi prefissi noti e anno
    slug_clean = re.sub(r'bpt[-_]?|elite[-_]?\d*|challenger[-_]?|futures[-_]?|\d{4}', '', slug, flags=re.IGNORECASE)
    slug_clean = slug_clean.strip("-_").replace("-", " ").replace("_", " ").title()
    if slug_clean:
        return slug_clean

    return "Location TBD"


# ─── CALCOLO PERIODI VIAGGIO ─────────────────────────────────────────────────────

def calcola_periodi(torneo: dict) -> dict:
    """
    Calcola tutti i periodi per un torneo confermato:
    - partenza (anticipo 4 o 6 giorni)
    - torneo
    - rientro (giorno dopo fine)
    - riposo (2 giorni dopo rientro)
    """
    # Assicura che le date siano oggetti date (potrebbero essere stringhe dall'API)
    d_start = torneo["date_start"]
    d_end   = torneo["date_end"]
    if isinstance(d_start, str):
        d_start = parse_api_date(d_start)
    if isinstance(d_end, str):
        d_end = parse_api_date(d_end)
    if not d_start or not d_end:
        raise ValueError(f"Date mancanti per torneo: {torneo.get('nome', '?')}")
    loc     = torneo["location"]

    anticipo   = 6 if is_oltreoceano(loc) else 4
    partenza   = d_start - timedelta(days=anticipo)
    rientro    = d_end + timedelta(days=1)
    riposo_end = rientro + timedelta(days=2)

    return {
        "nome":        torneo["nome"],
        "location":    loc,
        "oltreoceano": is_oltreoceano(loc),
        "partenza":    partenza,
        "date_start":  d_start,
        "date_end":    d_end,
        "rientro":     rientro,
        "riposo_end":  riposo_end,
    }


# ─── GENERAZIONE TESTO PER A3 ────────────────────────────────────────────────────

def format_date_it(d: date) -> str:
    giorni = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
    return f"{giorni[d.weekday()]} {d.day} {MESE_IT[:3].lower()}"


def genera_testo_calendario(tornei_mese: list[dict]) -> str:
    """
    Genera il testo formattato da copiare nel messaggio A3.
    """
    primo = date(ANNO, MESE_NUM, 1)
    ultimo = date(ANNO, MESE_NUM,
                  [31,28+int(ANNO%4==0),31,30,31,30,31,31,30,31,30,31][MESE_NUM-1])

    lines = []
    lines.append(f"CALENDARIO IMPEGNI — {MESE_LABEL.upper()}")
    lines.append("=" * 45)

    if not tornei_mese:
        lines.append("")
        lines.append("Nessun torneo BPT nel mese.")
        lines.append("")
        lines.append("📅 PERIODI:")
        lines.append(f"   {format_date_it(primo)} → {format_date_it(ultimo)} → Allenamento Pescara")
        lines.append("")
        lines.append("🗓 NOTE WEEKEND:")
        _aggiungi_weekend(lines, primo, ultimo, [])
        return "\n".join(lines)

    # Uno o più tornei
    for t in tornei_mese:
        p = calcola_periodi(t)
        tipo_trasferta = "oltreoceano (+6gg anticipo)" if p["oltreoceano"] else "vicina (+4gg anticipo)"

        lines.append("")
        lines.append(f"🏐 TORNEO: {p['nome']}")
        lines.append(f"   Luogo: {p['location']}")
        lines.append(f"   Trasferta: {tipo_trasferta}")
        lines.append(f"   Partenza:  {format_date_it(p['partenza'])} ({p['partenza'].day} {MESE_IT[:3]})")
        lines.append(f"   Torneo:    {p['date_start'].day}–{p['date_end'].day} {MESE_IT[:3]} {ANNO}")
        lines.append(f"   Rientro:   {format_date_it(p['rientro'])}")
        lines.append(f"   Riposo:    {format_date_it(p['rientro'] + timedelta(days=1))}–{format_date_it(p['riposo_end'])}")

    # Costruisci timeline periodi
    lines.append("")
    lines.append("📅 PERIODI:")

    # Raccogli tutti i periodi in ordine cronologico
    periodi = []
    cursore = primo

    # Taglia i tornei al mese (potrebbero iniziare il mese prima)
    for t in sorted(tornei_mese, key=lambda x: calcola_periodi(x)["partenza"]):
        p = calcola_periodi(t)

        # Partenza potrebbe essere nel mese precedente
        inizio_trasferta = max(p["partenza"], primo)
        fine_riposo      = min(p["riposo_end"], ultimo)

        if cursore < inizio_trasferta:
            periodi.append((cursore, inizio_trasferta - timedelta(days=1), "Allenamento Pescara"))

        if p["partenza"] >= primo:
            periodi.append((inizio_trasferta, p["date_start"] - timedelta(days=1), "Trasferta (viaggio)"))

        periodi.append((p["date_start"], p["date_end"], f"Torneo {p['location']}"))
        periodi.append((p["rientro"], p["rientro"], "Rientro"))

        if p["riposo_end"] <= ultimo:
            periodi.append((p["rientro"] + timedelta(days=1), p["riposo_end"], "Riposo"))
            cursore = p["riposo_end"] + timedelta(days=1)
        else:
            cursore = ultimo + timedelta(days=1)

    # Resto del mese dopo l'ultimo torneo
    if cursore <= ultimo:
        periodi.append((cursore, ultimo, "Allenamento Pescara"))

    for inizio, fine, label in periodi:
        if inizio == fine:
            lines.append(f"   {format_date_it(inizio)} → {label}")
        else:
            lines.append(f"   {format_date_it(inizio)} – {format_date_it(fine)} → {label}")

    # Weekend
    lines.append("")
    lines.append("🗓 NOTE WEEKEND:")
    _aggiungi_weekend(lines, primo, ultimo, tornei_mese)

    lines.append("")
    lines.append(f"[Generato automaticamente da script BPT — {date.today().strftime('%d/%m/%Y')}]")

    return "\n".join(lines)


def _aggiungi_weekend(lines, primo, ultimo, tornei):
    """Aggiunge note sui weekend del mese."""
    # Calcola periodi occupati (tornei + trasferte)
    occupati = set()
    for t in tornei:
        p = calcola_periodi(t)
        d = p["partenza"]
        while d <= p["riposo_end"]:
            occupati.add(d)
            d += timedelta(days=1)

    domeniche_libere = []
    sabati_liberi    = []
    sabati_occupati  = []

    d = primo
    while d <= ultimo:
        if d.weekday() == 6:  # domenica
            if d not in occupati:
                domeniche_libere.append(d.day)
        if d.weekday() == 5:  # sabato
            if d not in occupati:
                sabati_liberi.append(d.day)
            else:
                sabati_occupati.append(d.day)
        d += timedelta(days=1)

    mese_abbr = MESE_IT[:3].lower()
    if domeniche_libere:
        giorni_str = ", ".join(str(g) for g in domeniche_libere)
        lines.append(f"   Domeniche libere: {giorni_str} {mese_abbr}")
    if sabati_liberi:
        giorni_str = ", ".join(str(g) for g in sabati_liberi)
        lines.append(f"   Sabati probabilmente liberi: {giorni_str} {mese_abbr}")
    if sabati_occupati:
        giorni_str = ", ".join(str(g) for g in sabati_occupati)
        lines.append(f"   Sabati in trasferta/torneo: {giorni_str} {mese_abbr}")


# ─── GOOGLE DRIVE ───────────────────────────────────────────────────────────────

def get_drive_service():
    creds_b64  = os.environ["GOOGLE_CREDENTIALS"]
    creds_json = json.loads(base64.b64decode(creds_b64))
    scopes     = ["https://www.googleapis.com/auth/drive"]
    creds      = Credentials.from_service_account_info(creds_json, scopes=scopes)
    return build("drive", "v3", credentials=creds)


def drive_save_txt(service, content: str, filename: str, folder_id: str):
    """
    Salva il testo BPT su Drive come Google Doc nativo.
    Usa mimeType nativo per evitare storageQuotaExceeded dei service account.
    """
    import io
    from googleapiclient.http import MediaIoBaseUpload

    # Cerca file esistente
    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(
        q=query, fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    existing = results.get("files", [])

    # Carica come testo plain — il contenuto va nel body
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype="text/plain",
        resumable=False
    )

    if existing:
        service.files().update(
            fileId=existing[0]["id"],
            media_body=media,
            supportsAllDrives=True
        ).execute()
        print(f"    File aggiornato: {filename}")
    else:
        meta = {
            "name": filename,
            "parents": [folder_id],
            "mimeType": "application/vnd.google-apps.document"
        }
        service.files().create(
            body=meta,
            media_body=media,
            fields="id",
            supportsAllDrives=True
        ).execute()
        print(f"    File creato: {filename}")


# ─── SUPABASE ────────────────────────────────────────────────────────────────────

def supabase_update_bpt(testo: str, n_tornei: int):
    """Salva il testo calendario BPT in Supabase per la webapp."""
    supabase = create_client(SUPA_URL, SUPA_KEY)
    supabase.table("agent_states").upsert({
        "agent_id":        "bpt_calendar",
        "stato":           "done",
        "mese":            MESE_LABEL,
        "updated_at":      date.today().isoformat(),
        "calendario_bpt":  testo,
        "n_tornei":        n_tornei,
    }, on_conflict="agent_id").execute()
    print(f"    Supabase: bpt_calendar → done ({n_tornei} tornei)")


# ─── MAIN ─────────────────────────────────────────────────────────────────────────

def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page    = browser.new_page()

        # User agent realistico per evitare blocchi
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        })

        # 1. Carica lista tornei BPT
        tournaments = scrape_bpt_tournaments(page)

        if not tournaments:
            print("  ATTENZIONE: nessun torneo trovato sul sito BPT")
            testo = genera_testo_calendario([])
            browser.close()
        else:
            # 2. Filtra tornei nel mese da pianificare
            # L'API può già includere i giocatori — se non li include,
            # apre la pagina del torneo solo per quelli con date nel mese target
            primo_mese  = date(ANNO, MESE_NUM, 1)
            ultimo_mese = primo_mese + relativedelta(months=1) - timedelta(days=1)

            tornei_mese = []
            for t in tournaments:
                d_start = t.get("date_start")
                d_end   = t.get("date_end")

                if not d_start or not d_end:
                    continue

                # Calcola se il torneo interessa il mese target
                anticipo      = 6 if is_oltreoceano(t.get("location", "")) else 4
                data_partenza = d_start - timedelta(days=anticipo)
                data_riposo   = d_end + timedelta(days=3)

                if not (data_riposo >= primo_mese and data_partenza <= ultimo_mese):
                    continue  # torneo fuori dal mese target

                # Se l'API non ha già i giocatori, apri la pagina del torneo
                if not t.get("gianluca_presente"):
                    details = scrape_tournament_details(page, t)
                    t.update(details)

                if t.get("gianluca_presente"):
                    tornei_mese.append(t)
                    print(f"    ✅ {t['nome']} — {d_start} → {d_end} @ {t['location']}")
                else:
                    print(f"    ✗  {t['nome']} — Dal Corso non trovato")

                # Pausa anti-rate-limit tra un torneo e l'altro
                page.wait_for_timeout(4000)

        browser.close()

        # 3. Genera testo calendario
        testo = genera_testo_calendario(tornei_mese)
        print(f"\n  Calendario generato — {len(tornei_mese)} torneo/i nel mese")
        print("  " + "\n  ".join(testo.split("\n")[:8]))  # preview prime righe

        # 4. Salva su Supabase (testo leggibile dalla webapp)
        supabase_update_bpt(testo, len(tornei_mese))
        # Nota: il testo è disponibile nella webapp tramite Supabase
        # Non serve Drive per questo file — è testo breve

    print(f"\n✅ BPT Calendar completato — {MESE_LABEL}")
    print(f"   Tornei trovati: {len(tornei_mese)}")


if __name__ == "__main__":
    main()
