#!/usr/bin/env python3
"""
GDC IA TEAM — Notify Failures

Rete di sicurezza per crash "silenziosi" (token scaduto, credenziali
corrotte, Supabase irraggiungibile, pip install fallito, timeout —
qualunque cosa faccia interrompere uno script PRIMA che possa scrivere
lui stesso su activity_log). Vedi discussione Step 27/28: uno script
che crasha non può notificare "sto crashando" da solo.

Architettura "zero contatto": questo è un file completamente nuovo,
sganciato dai workflow che sorveglia. Nessuna modifica a
a1_monthly.yml, a1_mbs_watcher.yml, ig_token_refresh.yml,
a7_gmail_drafter.yml, pipeline_watcher.yml — il trigger `workflow_run`
in notify_failures.yml li ascolta per nome (campo `name:` esatto),
senza toccarli. Per sorvegliare un nuovo workflow in futuro, basta
aggiungerne il nome alla lista `workflows:` in notify_failures.yml.

Riusa VAPID_PRIVATE_KEY / VAPID_EMAIL già esistenti (creati per la push
di A1 in a1_monthly.py) — nessuna nuova chiave da generare.

Variabili d'ambiente richieste:
  SUPABASE_URL / SUPABASE_SERVICE_KEY
  VAPID_PRIVATE_KEY / VAPID_EMAIL
  WORKFLOW_NAME / RUN_URL   (passate dal workflow via github.event.workflow_run.*)
"""

import os
import json
import requests
from pywebpush import webpush, WebPushException

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
VAPID_PRIV   = os.environ['VAPID_PRIVATE_KEY']
VAPID_EMAIL  = os.environ['VAPID_EMAIL']

WORKFLOW_NAME = os.environ['WORKFLOW_NAME']
RUN_URL       = os.environ['RUN_URL']


def supabase_headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
    }


def log_activity():
    payload = {
        'agent_id': WORKFLOW_NAME,
        'tipo': 'errore',
        'titolo': f"Workflow fallito: {WORKFLOW_NAME}",
        'descrizione': "Run terminata con errore — controlla i log GitHub Actions per il dettaglio.",
        'link': RUN_URL,
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


def send_push_all():
    subs = get_subscriptions()
    if not subs:
        print("    Push: nessun dispositivo registrato — skip "
              "(normale finché la Fase 3/4 — attivazione push lato webapp — non è completata).")
        return

    title = f"⚠ Errore — {WORKFLOW_NAME}"
    body = "Un workflow è fallito. Tocca per i dettagli."

    for sub in subs:
        label = sub.get('device_label') or sub['endpoint'][:40]
        subscription_info = {
            'endpoint': sub['endpoint'],
            'keys': {'p256dh': sub['p256dh'], 'auth': sub['auth']}
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=json.dumps({'title': title, 'body': body, 'url': RUN_URL}),
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
    print(f"[NOTIFY-FAILURES] Workflow fallito rilevato: {WORKFLOW_NAME}")
    log_activity()
    send_push_all()


if __name__ == '__main__':
    main()
