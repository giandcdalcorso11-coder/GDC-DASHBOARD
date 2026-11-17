#!/usr/bin/env python3
"""
GDC IA TEAM — A2/A3/A4 Watcher

A2, A3 e A4 non girano come workflow GitHub schedulati: sono sessioni
Claude Code che Gianluca avvia lui stesso, e al termine la sessione
stessa scrive 'agent_states' -> 'done' (vedi docs/prompts/Agente{2,3,4}_
auto_prompt_*.md, sez. Chiusura) e 'activity_log' (già fatto in sessione,
questo script non lo tocca). Nessuno però manda una push quando succede:
a differenza della pipeline commerciale (companies -> trigger Postgres ->
repository_dispatch -> pipeline_notify.py), qui non esiste nessun evento
a cui agganciarsi, perché il cambiamento non arriva da un workflow.

Soluzione "zero contatto" come pipeline_watcher.py: un controllo leggero
e periodico (cron), non un'attesa attiva. Confronta agent_states.updated_at
con una colonna di guardia, agent_states.last_notified_at (Step 'Pagina
Impostazioni/Automazioni A2-A4'): se updated_at è più recente, è un
completamento non ancora notificato.

Variabili d'ambiente richieste:
  SUPABASE_URL / SUPABASE_SERVICE_KEY
  VAPID_PRIVATE_KEY / VAPID_EMAIL
"""

import os
import json
from datetime import datetime
import requests
from pywebpush import webpush, WebPushException


def parse_ts(ts):
    """PostgREST restituisce timestamptz come ISO 8601 con offset esplicito
    (es. '2026-11-15T15:34:18.67+00:00') — fromisoformat lo gestisce da
    Python 3.11 in su (stesso interprete usato dal workflow)."""
    return datetime.fromisoformat(ts)

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
VAPID_PRIV   = os.environ['VAPID_PRIVATE_KEY']
VAPID_EMAIL  = os.environ['VAPID_EMAIL']

WEBAPP_BASE = 'https://giandcdalcorso11-coder.github.io/GDC-DASHBOARD'

# Stessa famiglia di STEP_LABELS di pipeline_notify.py, qui per la catena
# social A1->A4. Chiavi notifica = quelle già definite in page_settings_v1.html.
AGENTS = {
    'a2': {
        'notif_key': 'a2_report',
        'titolo': 'A2 completato',
        'desc': 'Report mensile pronto, A3 sbloccato.',
        'link': f'{WEBAPP_BASE}/app/agenti/a2-analyst/page_agent_a2_v3.html',
    },
    'a3': {
        'notif_key': 'a3_piano',
        'titolo': 'A3 completato',
        'desc': 'Piano editoriale del mese pronto, A4 sbloccato.',
        'link': f'{WEBAPP_BASE}/app/agenti/a3-planner/page_agent_a3_v1.html',
    },
    'a4': {
        'notif_key': 'a4_brief',
        'titolo': 'A4 completato',
        'desc': 'Brief & script del mese pronti. Ultimo della catena A1->A4.',
        'link': f'{WEBAPP_BASE}/app/agenti/a4-brief/page_agent_a4_v1.html',
    },
}


def supabase_headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
    }


def get_agent_rows():
    ids = ','.join(AGENTS.keys())
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/agent_states"
        f"?agent_id=in.({ids})&select=agent_id,stato,updated_at,last_notified_at,mese",
        headers=supabase_headers(), timeout=10
    )
    if r.status_code != 200:
        print(f"⚠ Errore lettura agent_states: {r.status_code} {r.text}")
        return []
    return r.json()


def mark_notified(agent_id, updated_at):
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/agent_states?agent_id=eq.{agent_id}",
        json={'last_notified_at': updated_at},
        headers=supabase_headers(), timeout=10
    )


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


_notif_prefs_cache = None


def get_notification_prefs():
    """Preferenze da user_settings (pagina Impostazioni). Fail-open: riga assente
    o richiesta fallita = notifica considerata attiva."""
    global _notif_prefs_cache
    if _notif_prefs_cache is not None:
        return _notif_prefs_cache
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/user_settings?select=settings&order=updated_at.desc&limit=1",
            headers=supabase_headers(), timeout=10
        )
        if r.status_code == 200 and r.json():
            _notif_prefs_cache = (r.json()[0].get('settings') or {}).get('notifications') or {}
        else:
            _notif_prefs_cache = {}
    except Exception as e:
        print(f"⚠ Errore lettura user_settings: {e} — notifiche considerate attive (fail-open)")
        _notif_prefs_cache = {}
    return _notif_prefs_cache


def notification_enabled(key):
    prefs = get_notification_prefs()
    if prefs.get('master') is False:
        return False
    return prefs.get(key) is not False


def send_push_all(title, body, url, notif_key):
    if not notification_enabled(notif_key):
        print(f"    Push: notifica '{notif_key}' disattivata nelle Impostazioni — skip.")
        return
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
    rows = get_agent_rows()
    if not rows:
        print("Nessuna riga trovata per a2/a3/a4 — esco.")
        return

    for row in rows:
        agent_id = row['agent_id']
        cfg = AGENTS.get(agent_id)
        if not cfg:
            continue

        stato = row.get('stato')
        updated_at = row.get('updated_at')
        last_notified_at = row.get('last_notified_at')

        if stato != 'done':
            continue
        if last_notified_at is not None and parse_ts(updated_at) <= parse_ts(last_notified_at):
            continue

        mese = row.get('mese')
        titolo = f"✅ {cfg['titolo']}" + (f" — {mese}" if mese else "")
        print(f"[{agent_id.upper()}] Nuovo completamento rilevato ({updated_at}) — invio notifica.")
        send_push_all(titolo, cfg['desc'], cfg['link'], cfg['notif_key'])
        mark_notified(agent_id, updated_at)


if __name__ == '__main__':
    main()
