#!/usr/bin/env python3
"""
GDC IA TEAM — Export Scheda PDF

Caso raro ma reale: un collaboratore ha bisogno della scheda di
un'azienda (prodotta da Agente 5.2, ora una pagina HTML su Supabase,
tabella schede_aziendali — vedi Step "HTML invece di DOCX") e serve un
file vero da mandare, non un link alla webapp.

Trigger "zero contatto", stessa architettura di pipeline_notify.py:
un INSERT in scheda_pdf_requests fa scattare un trigger Postgres
(notify_scheda_pdf_requested) che manda un repository_dispatch via
pg_net — questo script riceve l'evento, apre la pagina HTML in un
browser headless (Playwright/Chromium), esporta un PDF fedele al
layout e lo carica sul bucket Storage privato "schede-pdf", generando
un link firmato temporaneo che la webapp mostra per il download.

Variabili d'ambiente richieste (passate dal workflow):
  SUPABASE_URL / SUPABASE_SERVICE_KEY
  REQUEST_ID / COMPANY_ID   (da github.event.client_payload.*)
"""

import os
import sys
from datetime import datetime, timezone
import requests
from playwright.sync_api import sync_playwright

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
REQUEST_ID   = os.environ['REQUEST_ID']
COMPANY_ID   = os.environ['COMPANY_ID']

BUCKET = 'schede-pdf'
SIGNED_URL_TTL = 3600  # 1 ora — e' un download una tantum, non un link da conservare


def supabase_headers(extra=None):
    h = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
    }
    if extra:
        h.update(extra)
    return h


def mark_request(status, pdf_url=None, error_message=None):
    payload = {'status': status}
    if pdf_url is not None:
        payload['pdf_url'] = pdf_url
    if error_message is not None:
        payload['error_message'] = error_message[:500]
    if status in ('done', 'error'):
        payload['completed_at'] = datetime.now(timezone.utc).isoformat()
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/scheda_pdf_requests?id=eq.{REQUEST_ID}",
        json=payload, headers=supabase_headers({'Prefer': 'return=minimal'}), timeout=10
    )
    if r.status_code not in (200, 204):
        print(f"⚠ Errore aggiornamento scheda_pdf_requests: {r.status_code} {r.text}")


def get_scheda_html():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/schede_aziendali?company_id=eq.{COMPANY_ID}&select=html",
        headers=supabase_headers(), timeout=10
    )
    if r.status_code != 200:
        raise RuntimeError(f"Errore lettura schede_aziendali: {r.status_code} {r.text}")
    rows = r.json()
    if not rows:
        return None
    return rows[0]['html']


def render_pdf(html, out_path):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until='networkidle')
        page.pdf(path=out_path, format='A4', print_background=True,
                 margin={'top': '12mm', 'bottom': '12mm', 'left': '10mm', 'right': '10mm'})
        browser.close()


def upload_pdf(local_path):
    with open(local_path, 'rb') as f:
        data = f.read()
    object_path = f"{COMPANY_ID}.pdf"
    r = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{object_path}",
        data=data,
        headers=supabase_headers({'Content-Type': 'application/pdf', 'x-upsert': 'true'}),
        timeout=30
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Errore upload Storage: {r.status_code} {r.text}")
    return object_path


def sign_pdf_url(object_path):
    r = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/sign/{BUCKET}/{object_path}",
        json={'expiresIn': SIGNED_URL_TTL},
        headers=supabase_headers(), timeout=10
    )
    if r.status_code != 200:
        raise RuntimeError(f"Errore generazione signed URL: {r.status_code} {r.text}")
    signed_path = r.json()['signedURL']
    return f"{SUPABASE_URL}/storage/v1{signed_path}"


def main():
    print(f"[EXPORT-SCHEDA-PDF] company_id={COMPANY_ID} request_id={REQUEST_ID}")

    html = get_scheda_html()
    if html is None:
        print("    Nessuna scheda trovata per questa azienda — errore non fatale.")
        mark_request('error', error_message='Scheda non trovata su Supabase per questa azienda.')
        return

    local_path = '/tmp/scheda.pdf'
    render_pdf(html, local_path)
    print(f"    ✅ PDF renderizzato ({os.path.getsize(local_path)} byte)")

    object_path = upload_pdf(local_path)
    print(f"    ✅ Caricato su Storage: {BUCKET}/{object_path}")

    pdf_url = sign_pdf_url(object_path)
    mark_request('done', pdf_url=pdf_url)
    print("    ✅ Richiesta segnata come 'done'")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"[EXPORT-SCHEDA-PDF] ERRORE: {e}")
        import traceback
        traceback.print_exc()
        mark_request('error', error_message=str(e))
        sys.exit(1)
