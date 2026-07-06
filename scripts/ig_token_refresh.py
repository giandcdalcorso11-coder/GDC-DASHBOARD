#!/usr/bin/env python3
"""
GDC IA TEAM — Script rinnovo token Instagram Graph API
Eseguito ogni ~50 giorni via GitHub Actions (cron), prima della scadenza
del long-lived token (60 giorni).

Flusso:
  1. Legge il token attuale (IG_ACCESS_TOKEN secret)
  2. Chiama l'endpoint Meta fb_exchange_token per ottenere un nuovo
     long-lived token (altri 60 giorni)
  3. Aggiorna il GitHub Secret IG_ACCESS_TOKEN con il nuovo valore
     (via GitHub API, richiede un secondo PAT con scope 'repo')
  4. Aggiorna Supabase con la data di scadenza prevista (per dashboard/monitoraggio)
  5. Se la chiamata fallisce, NON sovrascrive nulla — il vecchio token resta valido
     fino alla scadenza naturale e lo script può essere rilanciato manualmente

Secrets GitHub richiesti:
  IG_ACCESS_TOKEN     — token Instagram long-lived attuale (verrà sovrascritto)
  META_APP_ID         — ID app Meta
  META_APP_SECRET     — App Secret Meta
  GH_PAT_REPO         — Personal Access Token con scope 'repo' (per scrivere il secret)
  GH_OWNER            — username GitHub (es. giandcdalcorso11-coder)
  GH_REPO_NAME        — nome del repo (es. GDC-DASHBOARD)
  SUPABASE_URL          — URL progetto Supabase
  SUPABASE_SERVICE_KEY  — service_role key Supabase (bypassa la RLS; NON l'anon key)
"""

import os
import sys
import base64
import requests
from datetime import datetime, timedelta, timezone
from nacl import encoding, public


# ─── CONFIG ──────────────────────────────────────────────────────────
IG_TOKEN_CURRENT = os.environ["IG_ACCESS_TOKEN"]
APP_ID            = os.environ["META_APP_ID"]
APP_SECRET        = os.environ["META_APP_SECRET"]
GH_PAT            = os.environ["GH_PAT_REPO"]
GH_OWNER          = os.environ["GH_OWNER"]
GH_REPO           = os.environ["GH_REPO_NAME"]
SUPABASE_URL      = os.environ["SUPABASE_URL"]
SUPABASE_KEY      = os.environ["SUPABASE_SERVICE_KEY"]  # service_role: bypassa la RLS, mai l'anon key

GRAPH_API_VERSION = "v21.0"


# ─── STEP 1 — RINNOVA IL TOKEN ──────────────────────────────────────
def refresh_long_lived_token(current_token):
    """
    Chiama l'endpoint Meta per scambiare il token corrente con uno nuovo
    a lunga durata (60 giorni da oggi).
    """
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "fb_exchange_token": current_token
    }
    r = requests.get(url, params=params, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"Errore refresh token: {r.status_code} {r.text}")

    data = r.json()
    new_token = data.get("access_token")
    expires_in = data.get("expires_in", 5184000)  # default 60gg in secondi

    if not new_token:
        raise RuntimeError(f"Risposta Meta senza access_token: {data}")

    return new_token, expires_in


# ─── STEP 2 — AGGIORNA GITHUB SECRET ────────────────────────────────
def get_repo_public_key():
    url = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/actions/secrets/public-key"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json"
    }
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"Errore lettura public key repo: {r.status_code} {r.text}")
    return r.json()  # { key_id, key }


def encrypt_secret(public_key_b64, secret_value):
    """Cripta il valore del secret con la public key del repo (libsodium/NaCl)."""
    public_key = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def update_github_secret(secret_name, secret_value):
    """Crea o aggiorna un GitHub Actions secret nel repo."""
    key_data = get_repo_public_key()
    encrypted_value = encrypt_secret(key_data["key"], secret_value)

    url = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/actions/secrets/{secret_name}"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json"
    }
    payload = {
        "encrypted_value": encrypted_value,
        "key_id": key_data["key_id"]
    }
    r = requests.put(url, headers=headers, json=payload, timeout=15)
    if r.status_code not in (201, 204):
        raise RuntimeError(f"Errore aggiornamento secret {secret_name}: {r.status_code} {r.text}")
    print(f"[IG-REFRESH] Secret '{secret_name}' aggiornato su GitHub ({r.status_code})")


# ─── STEP 3 — SUPABASE LOG ──────────────────────────────────────────
def update_supabase_token_status(expires_at_iso, success=True, error_msg=None):
    """Scrive lo stato dell'ultimo rinnovo in una tabella di log/monitoraggio."""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }
    payload = {
        "id": "ig_token",
        "last_refreshed_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at_iso,
        "status": "ok" if success else "error",
        "error_message": error_msg
    }
    url = f"{SUPABASE_URL}/rest/v1/token_status?on_conflict=id"
    r = requests.post(url, headers=headers, json=payload, timeout=10)
    if r.status_code not in (200, 201, 204):
        print(f"[IG-REFRESH] Warning Supabase token_status: {r.status_code} {r.text}")
    else:
        print(f"[IG-REFRESH] Supabase token_status aggiornato")


# ─── MAIN ────────────────────────────────────────────────────────────
def main():
    print(f"[IG-REFRESH] Start — {datetime.now(timezone.utc).isoformat()}")

    try:
        new_token, expires_in = refresh_long_lived_token(IG_TOKEN_CURRENT)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        print(f"[IG-REFRESH] Nuovo token ottenuto, valido fino a {expires_at.isoformat()}")

        update_github_secret("IG_ACCESS_TOKEN", new_token)
        update_supabase_token_status(expires_at.isoformat(), success=True)

        print(f"[IG-REFRESH] Completato con successo.")

    except Exception as e:
        print(f"[IG-REFRESH] ERRORE: {e}")
        try:
            update_supabase_token_status(
                expires_at_iso=None,
                success=False,
                error_msg=str(e)
            )
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
