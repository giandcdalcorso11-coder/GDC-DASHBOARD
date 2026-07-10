#!/usr/bin/env python3
"""
GDC IA TEAM — Pipeline Notify

Riceve il payload inviato dal trigger Postgres su companies
(notify_company_step_change, vedi migrazione Step 28) tramite
repository_dispatch (event_type: company-step-changed) e:
  1) scrive una riga leggibile su activity_log
  2) invia una push a tutti i dispositivi in push_subscriptions

Architettura "zero contatto": nessun prompt agente coinvolto. Il
trigger scatta perché A5.1/A5.2/A6.1/A6.2/A7/pipeline_watcher scrivono
già step_attuale come parte del loro lavoro normale — questo script si
limita a tradurre il numero di step in un messaggio comprensibile.

Variabili d'ambiente richieste (passate dal workflow):
  SUPABASE_URL / SUPABASE_SERVICE_KEY
  VAPID_PRIVATE_KEY / VAPID_EMAIL
  COMPANY_ID / COMPANY_NOME / STEP_PRECEDENTE / STEP_NUOVO
"""

import os
import json
import requests
from pywebpush import webpush, WebPushException

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
VAPID_PRIV   = os.environ['VAPID_PRIVATE_KEY']
VAPID_EMAIL  = os.environ['VAPID_EMAIL']

COMPANY_ID       = os.environ['COMPANY_ID']
COMPANY_NOME     = os.environ.get('COMPANY_NOME', '?')
STEP_PRECEDENTE  = os.environ.get('STEP_PRECEDENTE', '')
STEP_NUOVO       = os.environ.get('STEP_NUOVO', '')

WEBAPP_BASE = 'https://giandcdalcorso11-coder.github.io/GDC-DASHBOARD'

# Etichette leggibili per ogni step della pipeline a 13 step.
STEP_LABELS = {
    '1':  ('A5.1', 'Trovata', 'Nuova azienda trovata e scritta a sistema.'),
    '2':  ('A5.2', 'Scheda', 'Scheda aziendale pronta.'),
    '3':  ('A6.1', 'Media kit', 'Media kit pronto.'),
    '4':  ('Pipeline Watcher', 'Approvato', 'PDF approvato rilevato su Drive.'),
    '5':  ('A6.2', 'Testo mail', 'Testo della mail commerciale pronto.'),
    '6':  ('A7', 'Bozza Gmail', 'Bozza email creata su Gmail.'),
    '7':  ('Pipeline Watcher', 'Mail inviata', 'Invio della mail rilevato.'),
    '8':  ('A6.2', 'Risposta', "L'azienda ha risposto."),
    '9':  ('A6.2', 'Gestita', 'Risposta gestita.'),
    '10': ('A6.2', 'Trattativa', 'Trattativa avviata.'),
    '11': ('A6.2', 'Accordo', 'Accordo raggiunto.'),
    '12': ('A6.2', 'Contratto', 'Contratto firmato.'),
    '13': ('A6.2', 'Rifiutato', "L'azienda ha rifiutato."),
}


def supabase_headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
    }


def log_activity(agent_id, titolo, descrizione, link):
    payload = {
        'agent_id': agent_id,
        'tipo': 'step',
        'titolo': titolo,
        'descrizione': descrizione,
        'link': link,
    }
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/activity_log",
        json=payload, headers=supabase_headers(), timeout=10
    )
    if r.status_code not in (200, 201, 204):
        print(f"⚠ Errore scrittura activity_log: {r.status_code} {r.text}")
    else:
        print("✅ Scritto su activity_log")


def get_subscriptions():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/push_subscriptions"
        f"?select=endpoint,p256dh,auth,device_label",
        headers=supabase_headers(), timeout=10
    )
    if r.status_code != 200:
        print(f"⚠ Errore lettura push_subscriptions: {r.status_code} {r.text}")
        return []
    return r.json()


def delete_subscription(endpoint):
    url = f"{SUPABASE_URL}/rest/v1/push_subscriptions?endpoint=eq.{endpoint}"
    requests.delete(url, headers=supabase_headers(), timeout=10)


def send_push_all(title, body, url):
    subs = get_subscriptions()
    if not subs:
        print("    Push: nessun dispositivo registrato — skip.")
        return

    for sub in subs:
        label = sub.get('device_label') or sub['endpoint'][:40]
        subscription_info = {
            'endpoint': sub['endpoint'],
            'keys': {'p256dh': sub['p256dh'], 'auth': sub['auth']}
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=json.dumps({'title': title, 'body': body, 'url': url}),
                vapid_private_key=VAPID_PRIV,
                vapid_claims={'sub': f"mailto:{VAPID_EMAIL}"}
            )
            print(f"    ✅ Push inviata a '{label}'")
        except WebPushException as e:
            status = getattr(e.response, 'status_code', None)
            print(f"    ⚠ Push fallita per '{label}' (status {status}): {e}")
            if status in (404, 410):
                delete_subscription(sub['endpoint'])
                print(f"      Subscription scaduta rimossa da Supabase ('{label}').")


def main():
    print(f"[PIPELINE-NOTIFY] {COMPANY_NOME}: step {STEP_PRECEDENTE} -> {STEP_NUOVO}")

    agent_id, nome_step, descrizione_base = STEP_LABELS.get(
        STEP_NUOVO, ('Pipeline', f'Step {STEP_NUOVO}', 'Avanzamento pipeline.')
    )
    titolo = f"{COMPANY_NOME} — {nome_step}"
    descrizione = descrizione_base
    link = f"{WEBAPP_BASE}/page_company_v2.html?id={COMPANY_ID}"

    log_activity(agent_id, titolo, descrizione, link)
    send_push_all(titolo, descrizione, link)


if __name__ == '__main__':
    main()
