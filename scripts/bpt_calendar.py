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

DRIVE_FOLDER_A3 = os.environ["DRIVE_FOLDER_A3"]
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
PLAYER_SEARCH   = "dal corso"   # cerca case-insensitive

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

def scrape_bpt_tournaments(page) -> list[dict]:
    """
    Carica la pagina BPT e estrae tutti i tornei visibili.
    Restituisce lista di dict: {nome, location, date_start, date_end, url}
    """
    print(f"  → Carico pagina BPT: {BPT_URL}")
    page.goto(BPT_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)  # attesa rendering JS tornei

    # Aspetta che i tornei siano caricati (elemento con le card eventi)
    try:
        page.wait_for_selector("[class*='event'], [class*='competition'], [class*='tournament']",
                               timeout=15000)
    except PlaywrightTimeout:
        print("    ATTENZIONE: elementi eventi non trovati, provo con testo grezzo")

    # Cerca tutti i link a pagine di tornei individuali
    # Il sito usa URL tipo /beachvolleyball/competitions/beach-pro-tour/events/[nome-torneo]/
    links = page.evaluate("""
        () => {
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            const tournamentLinks = anchors
                .filter(a => a.href.includes('/beach-pro-tour/') &&
                             a.href.includes('/events/') &&
                             !a.href.includes('#') && a.href.split('/').filter(Boolean).length > 6)
                .map(a => ({
                    href: a.href,
                    text: a.textContent.trim()
                }));
            // Deduplica per href
            const seen = new Set();
            return tournamentLinks.filter(l => {
                if (seen.has(l.href)) return false;
                seen.add(l.href);
                return true;
            });
        }
    """)

    # Se non trova link diretti, prova a leggere le card con date
    if not links:
        print("    Nessun link torneo trovato, provo selettori alternativi")
        links = page.evaluate("""
            () => {
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                return anchors
                    .filter(a => a.href.includes('beach-pro-tour') &&
                                 a.href.length > 60)
                    .map(a => ({ href: a.href, text: a.textContent.trim() }))
                    .slice(0, 50);
            }
        """)

    print(f"    Trovati {len(links)} link tornei candidati")

    tournaments = []
    for link in links:
        url = link["href"]
        text = link["text"]

        # Estrai info dal testo del link o dall'URL
        # Formato tipico URL: .../events/bpt-elite16-hamburg-2026/
        slug = url.rstrip("/").split("/")[-1]

        tournaments.append({
            "nome": text if text else slug,
            "slug": slug,
            "url": url,
            "date_start": None,
            "date_end": None,
            "location": "",
        })

    return tournaments


def scrape_tournament_details(page, tournament: dict) -> dict:
    """
    Entra nella pagina del singolo torneo e recupera:
    - date precise
    - location
    - se "Dal Corso" è nella lista partecipanti
    """
    url = tournament["url"]
    print(f"    Analizzo: {url}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except PlaywrightTimeout:
        print(f"      Timeout su {url}, skip")
        return tournament

    # Leggi tutto il testo della pagina
    full_text = page.inner_text("body").lower()

    # Controlla presenza "Dal Corso"
    tournament["gianluca_presente"] = PLAYER_SEARCH in full_text

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
    d_start = torneo["date_start"]
    d_end   = torneo["date_end"]
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
    """Salva o aggiorna un file TXT su Drive."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                     delete=False, encoding="utf-8") as f:
        f.write(content)
        tmp_path = f.name

    media = MediaFileUpload(tmp_path, mimetype="text/plain")

    # Cerca file esistente
    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get("files", [])

    if files:
        service.files().update(fileId=files[0]["id"], media_body=media).execute()
        print(f"    File aggiornato: {filename}")
    else:
        meta = {"name": filename, "parents": [folder_id]}
        service.files().create(body=meta, media_body=media, fields="id").execute()
        print(f"    File creato: {filename}")

    os.unlink(tmp_path)


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
            # 2. Filtra tornei nel mese da pianificare e cerca "Dal Corso"
            tornei_mese = []
            for t in tournaments:
                # Controlla se il torneo è nel mese target (o a cavallo)
                details = scrape_tournament_details(page, t)

                if not details.get("gianluca_presente"):
                    continue

                d_start = details.get("date_start")
                d_end   = details.get("date_end")

                if not d_start or not d_end:
                    print(f"      Date non trovate per {t['slug']}, skip")
                    continue

                # Includi se il torneo ricade nel mese da pianificare
                # (anche se inizia nel mese corrente — trasferta potrebbe iniziare nel mese target)
                primo_mese  = date(ANNO, MESE_NUM, 1)
                ultimo_mese = primo_mese + relativedelta(months=1) - timedelta(days=1)

                # Calcola partenza per capire se interessa il mese target
                anticipo     = 6 if is_oltreoceano(details.get("location", "")) else 4
                data_partenza = d_start - timedelta(days=anticipo)
                data_riposo  = d_end + timedelta(days=3)  # rientro + 2 riposo

                if data_riposo >= primo_mese and data_partenza <= ultimo_mese:
                    tornei_mese.append(details)
                    print(f"    ✅ Torneo confermato: {details['slug']} — {d_start} → {d_end} @ {details['location']}")

        browser.close()

        # 3. Genera testo calendario
        testo = genera_testo_calendario(tornei_mese)
        print(f"\n  Calendario generato — {len(tornei_mese)} torneo/i nel mese")
        print("  " + "\n  ".join(testo.split("\n")[:8]))  # preview prime righe

        # 4. Salva su Drive
        drive_service = get_drive_service()
        filename      = f"bpt_{MESE_IT_LOWER}_{ANNO}.txt"
        drive_save_txt(drive_service, testo, filename, DRIVE_FOLDER_A3)

        # 5. Aggiorna Supabase
        supabase_update_bpt(testo, len(tornei_mese))

    print(f"\n✅ BPT Calendar completato — {MESE_LABEL}")
    print(f"   Tornei trovati: {len(tornei_mese)}")


if __name__ == "__main__":
    main()
