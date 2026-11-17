#!/usr/bin/env python3
"""
GDC IA TEAM — Credential Health Check

Punto di rischio emerso durante l'audit del Team Commerciale (Step 10):
tutta la catena A5-A7 + Pipeline Watcher/Notify dipende da credenziali a
lunga vita (PAT GitHub, service account Google, refresh token Gmail) che
possono scadere o essere revocate senza che nessuno script esistente lo
noti — uno script che fallisce per un token scaduto fallisce PRIMA di
poter scrivere lui stesso un errore su activity_log (stessa classe di
problema già risolta per i crash in generale da notify_failures.py,
Step 27/28, ma quella rete scatta solo DOPO che qualcosa è già rotto).

Questo script testa attivamente, senza modificare nulla, le tre
credenziali più a rischio:
  1. github_repo_dispatch_pat (Vault) — via RPC check_github_pat_health(),
     che fa la stessa identica chiamata del trigger Postgres
     (repository_dispatch con un event_type che non corrisponde a nessun
     listener configurato, quindi non avvia alcun workflow) senza che il
     PAT transiti mai fuori dal database.
  2. Service account Google (Drive) — drive.about().get(), chiamata
     innocua che richiede solo credenziali valide.
  3. Refresh token Gmail — gmail.users().getProfile(), stesso principio.

Se una fallisce, il risultato va su token_status (stesso schema già
usato da ig_token_refresh.py per il token Instagram) e lo script esce
con errore — così la rete di sicurezza notify_failures.py (già esistente,
basta aggiungere questo workflow alla sua watch-list) manda la push
"Errore automazione" senza bisogno di duplicare qui la logica di invio.

Pensato per girare una volta al giorno (le credenziali non scadono
minuto per minuto) via cron (credential_health_check.yml).

Variabili d'ambiente richieste:
  SUPABASE_URL / SUPABASE_SERVICE_KEY
  GOOGLE_CREDENTIALS     — service account JSON, base64
  GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN
"""

import os
import json
import base64
from datetime import datetime, timezone

import requests
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
GOOGLE_CREDENTIALS  = os.environ['GOOGLE_CREDENTIALS']
GMAIL_CLIENT_ID     = os.environ['GMAIL_CLIENT_ID']
GMAIL_CLIENT_SECRET = os.environ['GMAIL_CLIENT_SECRET']
GMAIL_REFRESH_TOKEN = os.environ['GMAIL_REFRESH_TOKEN']


def supabase_headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal,resolution=merge-duplicates'
    }


def write_status(cred_id, ok, error_msg=None):
    payload = {
        'id': cred_id,
        'status': 'ok' if ok else 'error',
        'error_message': error_msg,
        'last_refreshed_at': datetime.now(timezone.utc).isoformat(),
    }
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/token_status?on_conflict=id",
        json=payload, headers=supabase_headers(), timeout=10
    )
    if r.status_code not in (200, 201, 204):
        print(f"⚠ Errore scrittura token_status per '{cred_id}': {r.status_code} {r.text}")


def check_github_pat():
    print("[HEALTH] Controllo github_repo_dispatch_pat...")
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/check_github_pat_health",
            json={}, headers=supabase_headers(), timeout=15
        )
        if r.status_code != 200:
            raise RuntimeError(f"RPC fallita: {r.status_code} {r.text}")
        status_code = r.json().get('status_code')
        if status_code != 204:
            raise RuntimeError(f"GitHub ha risposto {status_code} invece di 204 — PAT scaduto/revocato o permessi insufficienti.")
        print(f"    ✅ OK (GitHub status {status_code})")
        write_status('github_repo_dispatch_pat', True)
        return True
    except Exception as e:
        print(f"    ⚠ FALLITO: {e}")
        write_status('github_repo_dispatch_pat', False, str(e)[:500])
        return False


def check_google_service_account():
    print("[HEALTH] Controllo service account Google (Drive)...")
    try:
        creds_json = base64.b64decode(GOOGLE_CREDENTIALS).decode('utf-8')
        creds_info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_info, scopes=['https://www.googleapis.com/auth/drive']
        )
        drive = build('drive', 'v3', credentials=creds)
        about = drive.about().get(fields='user').execute()
        print(f"    ✅ OK (account: {about.get('user', {}).get('emailAddress', '?')})")
        write_status('google_service_account', True)
        return True
    except Exception as e:
        print(f"    ⚠ FALLITO: {e}")
        write_status('google_service_account', False, str(e)[:500])
        return False


def check_gmail_refresh_token():
    print("[HEALTH] Controllo refresh token Gmail...")
    try:
        creds = Credentials(
            token=None,
            refresh_token=GMAIL_REFRESH_TOKEN,
            client_id=GMAIL_CLIENT_ID,
            client_secret=GMAIL_CLIENT_SECRET,
            token_uri='https://oauth2.googleapis.com/token',
            scopes=['https://www.googleapis.com/auth/gmail.compose']
        )
        creds.refresh(Request())
        gmail = build('gmail', 'v1', credentials=creds)
        profile = gmail.users().getProfile(userId='me').execute()
        print(f"    ✅ OK (account: {profile.get('emailAddress', '?')})")
        write_status('gmail_refresh_token', True)
        return True
    except Exception as e:
        print(f"    ⚠ FALLITO: {e}")
        write_status('gmail_refresh_token', False, str(e)[:500])
        return False


def main():
    print(f"[HEALTH] Start — {datetime.now(timezone.utc).isoformat()}")

    results = {
        'github_repo_dispatch_pat': check_github_pat(),
        'google_service_account': check_google_service_account(),
        'gmail_refresh_token': check_gmail_refresh_token(),
    }

    failed = [k for k, ok in results.items() if not ok]
    if failed:
        print(f"[HEALTH] Fine — credenziali non valide: {failed}")
        raise SystemExit(1)

    print("[HEALTH] Fine — tutte le credenziali valide.")


if __name__ == '__main__':
    main()
