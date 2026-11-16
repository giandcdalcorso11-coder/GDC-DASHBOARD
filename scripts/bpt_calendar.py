"""
GDC IA TEAM — Script BPT Calendar
Gira il 2 del mese in parallelo ad A1, pianifica il mese successivo
(mese corrente + 1, salvo override manuale).

Fonte dati: fivbeach.com — sito ufficiale del circuito pro di beach volley.
Ogni pagina incorpora un blob JSON (attributo data-page, Inertia.js) già
pulito e leggibile con una normale richiesta HTTP: nessun browser/Playwright
necessario, né per il calendario né per la lista iscritti dei singoli
tornei.

Flusso:
1. Scarica il calendario maschile da fivbeach.com per l'anno del mese
   target ± 1 (per non perdere tornei il cui margine di viaggio sfora
   a cavallo di fine/inizio anno).
2. Esclude solo le categorie strutturalmente non pertinenti per un
   giocatore pro adulto (tour nazionali, giovanili U18/U20/U22, eventi
   multi-sport). NON filtra per livello/tier (Elite, Challenge, World
   Series, ...): la FIVB sta cambiando quella tassonomia nel passaggio
   dal Beach Pro Tour alla nuova FIVB Beach World Series (2026→2027), e
   un filtro basato sui nomi di livello attuali si romperebbe in silenzio
   a ogni cambio di nome federale. Il livello su cui filtriamo davvero è
   "il torneo cade nella finestra di viaggio del mese target?", poi si
   verifica l'iscrizione effettiva.
3. Per ogni torneo la cui finestra [partenza-anticipo, rientro+riposo]
   tocca il mese target, scarica la pagina del torneo e controlla la
   lista iscritti per "Dal Corso" / "Cottafava".
4. Genera il testo calendario formattato per A3.
5. Aggiorna Supabase:
   - bpt_calendars (upsert per mese_num+anno) → fonte usata da A3/home
     per costruire il messaggio del mese effettivamente pianificato
   - agent_states.bpt_calendar → solo per i pannelli informativi
     "ultimo ciclo generato" (es. pagina A1), non usare per il messaggio A3

Secrets GitHub richiesti:
  SUPABASE_URL          — URL progetto Supabase
  SUPABASE_SERVICE_KEY  — service_role key Supabase (bypassa la RLS; NON l'anon key)

(GOOGLE_CREDENTIALS / DRIVE_FOLDER_A3 non servono più: il testo è letto
dalla webapp direttamente da Supabase, non da un file su Drive.)
"""

import os
import re
import json
import html
import time
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

import requests
from supabase import create_client


# ─── CONFIG ────────────────────────────────────────────────────────────────────

SUPA_URL = os.environ["SUPABASE_URL"]
SUPA_KEY = os.environ["SUPABASE_SERVICE_KEY"]  # service_role: bypassa la RLS, mai l'anon key

# Mese da pianificare = mese corrente + 1, salvo override manuale
# (2/8/2026: aggiunto override — la riga calendario_bpt su Supabase e'
# unica e viene sempre sovrascritta dal prossimo run automatico; se A3
# viene lanciato in ritardo rispetto al ciclo normale, il mese giusto
# puo' risultare gia' sovrascritto da quello successivo. BPT_TARGET_MONTH
# (formato YYYY-MM) permette di rigenerare un mese specifico su richiesta.)
today    = date.today()
override = os.environ.get("BPT_TARGET_MONTH", "").strip()
if override:
    target = date.fromisoformat(override + "-01")
else:
    target = today + relativedelta(months=1)
MESE_NUM = target.month
ANNO     = target.year
MESI_IT  = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
            "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]
MESE_IT       = MESI_IT[MESE_NUM]
MESE_LABEL    = f"{MESE_IT} {ANNO}"

PLAYER_SEARCH_TERMS = ["dal corso", "cottafava"]

FIVBEACH_BASE = "https://fivbeach.com"
HTTP_HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept":     "text/html",
}

# Categorie strutturalmente non pertinenti per un giocatore pro adulto.
# Volutamente NON includiamo qui i nomi di livello del circuito pro
# (Elite, Challenge, World Series, Major, ...) — vedi nota in testa al file.
EXCLUDE_TYPE_KEYWORDS = [
    "national tour", "youth", "u18", "u20", "u22", "zonal tour", "multiple sports",
]


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
    loc = (location or "").lower()
    return any(kw in loc for kw in OLTREOCEANO_KEYWORDS)


# ─── FIVBEACH.COM — LETTURA DATI ────────────────────────────────────────────────

def fetch_page_json(path: str, params: dict | None = None) -> dict:
    """
    Scarica una pagina fivbeach.com e ne estrae il blob JSON incorporato
    nell'attributo data-page (pagina Inertia.js, server-rendered —
    nessun browser necessario).
    """
    resp = requests.get(f"{FIVBEACH_BASE}{path}", headers=HTTP_HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    m = re.search(r'data-page="(.*)"', resp.text, re.S)
    if not m:
        raise RuntimeError(f"Blob data-page non trovato su {path}")
    return json.loads(html.unescape(m.group(1)))


def fetch_tournaments_for_year(year: int) -> list[dict]:
    """Lista tornei maschili per un anno (homepage calendario fivbeach.com)."""
    data = fetch_page_json("/", params={"year": year, "gender": "M"})
    return data.get("props", {}).get("tournaments", [])


def is_excluded_type(tipo: str) -> bool:
    t = (tipo or "").lower()
    return any(kw in t for kw in EXCLUDE_TYPE_KEYWORDS)


def parse_iso_date(s) -> date | None:
    """fivbeach.com restituisce sempre date in formato 'YYYY-MM-DD'."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def scrape_all_tournaments() -> list[dict]:
    """
    Scarica i tornei maschili per l'anno del mese target ± 1 (copre i
    tornei il cui margine di viaggio sfora a cavallo di fine/inizio anno),
    deduplica per id torneo e scarta solo le categorie non pertinenti.
    """
    per_id: dict[int, dict] = {}
    for y in (ANNO - 1, ANNO, ANNO + 1):
        try:
            for item in fetch_tournaments_for_year(y):
                per_id[item["no"]] = item
        except Exception as e:
            print(f"    ATTENZIONE: impossibile scaricare il calendario {y}: {e}")

    tornei = []
    for item in per_id.values():
        if is_excluded_type(item.get("type")):
            continue
        d_start = parse_iso_date(item.get("startDate"))
        d_end   = parse_iso_date(item.get("endDate"))
        if not d_start or not d_end:
            continue
        citta    = (item.get("city") or "").strip()
        paese    = (item.get("country") or "").strip()
        location = ", ".join(p for p in (citta, paese) if p) or "Location TBD"
        tornei.append({
            "no":                item["no"],
            "nome":              item.get("name") or item.get("title") or item.get("code") or "Torneo",
            "tipo":              item.get("type"),
            "location":          location,
            "date_start":        d_start,
            "date_end":          d_end,
            "gianluca_presente": False,
        })

    print(f"    Tornei scaricati (esclusi tour nazionali/giovanili/multisport): {len(tornei)}")
    return tornei


def check_player_in_tournament(no: int) -> bool:
    """Controlla la lista iscritti del torneo per 'Dal Corso' / 'Cottafava'."""
    try:
        data = fetch_page_json(f"/tournaments/{no}")
    except Exception as e:
        print(f"      ATTENZIONE: impossibile leggere la pagina del torneo {no}: {e}")
        return False
    teams = data.get("props", {}).get("teams") or []
    for team in teams:
        blob = json.dumps(team).lower()
        if any(term in blob for term in PLAYER_SEARCH_TERMS):
            return True
    return False


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
    """Formatta data in italiano: 'lun 27 giu'. Usa il mese reale della data."""
    giorni    = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
    mesi_abbr = ["", "gen", "feb", "mar", "apr", "mag", "giu",
                 "lug", "ago", "set", "ott", "nov", "dic"]
    return f"{giorni[d.weekday()]} {d.day} {mesi_abbr[d.month]}"


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
        lines.append(f"   Partenza:  {format_date_it(p['partenza'])}")
        mesi_abbr_t = ["","Gen","Feb","Mar","Apr","Mag","Giu","Lug","Ago","Set","Ott","Nov","Dic"]
        lines.append(f"   Torneo:    {p['date_start'].day}–{p['date_end'].day} {mesi_abbr_t[p['date_start'].month]} {p['date_start'].year}")
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


# ─── SUPABASE ────────────────────────────────────────────────────────────────────

def supabase_update_bpt(testo: str, n_tornei: int):
    """
    Salva il testo calendario BPT in Supabase.

    Scrive in DUE posti, con scopi distinti:
    1. bpt_calendars — riga STORICIZZATA per mese+anno (upsert su chiave
       mese_num+anno). E' la fonte usata da page_home_v25.html e
       page_agent_a3_v1.html per costruire il messaggio di A3: interrogano
       esplicitamente il mese che stanno pianificando, quindi non c'e' più
       un'unica riga che puo' essere sovrascritta dal ciclo successivo.
    2. agent_states (riga agent_id='bpt_calendar') — mantenuta SOLO per i
       pannelli informativi "ultimo ciclo generato" (es. page_agent_a1_v1.html),
       che mostrano volutamente l'ultimo dato disponibile, non un mese
       specifico. Non usare mai questa riga per costruire il messaggio A3.
    """
    supabase = create_client(SUPA_URL, SUPA_KEY)

    supabase.table("bpt_calendars").upsert({
        "mese_num":   MESE_NUM,
        "anno":       ANNO,
        "mese_label": MESE_LABEL,
        "testo":      testo,
        "n_tornei":   n_tornei,
        "updated_at": date.today().isoformat(),
    }, on_conflict="mese_num,anno").execute()
    print(f"    Supabase: bpt_calendars[{MESE_NUM:02d}/{ANNO}] → salvato ({n_tornei} tornei)")

    supabase.table("agent_states").upsert({
        "agent_id":        "bpt_calendar",
        "stato":           "done",
        "mese":            MESE_LABEL,
        "updated_at":      date.today().isoformat(),
        "calendario_bpt":  testo,
        "n_tornei":        n_tornei,
    }, on_conflict="agent_id").execute()
    print(f"    Supabase: agent_states.bpt_calendar → done (solo per pannelli 'ultimo ciclo')")


# ─── MAIN ─────────────────────────────────────────────────────────────────────────

def main():
    print(f"▶ BPT Calendar — mese da pianificare: {MESE_LABEL}")

    tutti = scrape_all_tournaments()

    primo_mese  = date(ANNO, MESE_NUM, 1)
    ultimo_mese = primo_mese + relativedelta(months=1) - timedelta(days=1)

    tornei_mese = []
    for t in tutti:
        anticipo      = 6 if is_oltreoceano(t["location"]) else 4
        data_partenza = t["date_start"] - timedelta(days=anticipo)
        data_riposo   = t["date_end"] + timedelta(days=3)

        if not (data_riposo >= primo_mese and data_partenza <= ultimo_mese):
            continue  # torneo fuori dal mese target

        time.sleep(0.3)  # cortesia verso il server, non serve anti-rate-limit aggressivo
        if check_player_in_tournament(t["no"]):
            t["gianluca_presente"] = True
            tornei_mese.append(t)
            print(f"    ✅ {t['nome']} — {t['date_start']} → {t['date_end']} @ {t['location']}")
        else:
            print(f"    ✗  {t['nome']} ({t['tipo']}) — Dal Corso non trovato")

    testo = genera_testo_calendario(tornei_mese)
    print(f"\n  Calendario generato — {len(tornei_mese)} torneo/i nel mese")
    print("  " + "\n  ".join(testo.split("\n")[:8]))  # preview prime righe

    supabase_update_bpt(testo, len(tornei_mese))
    # Nota: il testo è disponibile nella webapp tramite Supabase — non serve Drive

    print(f"\n✅ BPT Calendar completato — {MESE_LABEL}")
    print(f"   Tornei trovati: {len(tornei_mese)}")


if __name__ == "__main__":
    main()
