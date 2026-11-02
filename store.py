"""Firebase access via REST.

Config comes ONLY from environment variables — never hardcode secrets:
    FIREBASE_API_KEY   (Web API key, from the theme's firebase config)
    FIREBASE_DB_URL    (e.g. https://sr-tech-industry-default-rtdb.firebaseio.com)
    BOT_EMAIL          (bot user's email)
    BOT_PASSWORD       (bot user's password)

The site's RTDB rules already allow any authenticated user to write cms,
so a dedicated bot user (created in Firebase console -> Authentication)
is enough. Public read needs no auth.
"""

import os
import sys

import requests

TIMEOUT = 20


def _env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"missing required env var: {name}")
    return v


def signin(api_key=None, email=None, password=None):
    """Email/password sign-in -> Firebase idToken. Raises with the API's error message."""
    api_key = api_key or _env("FIREBASE_API_KEY")
    email = email or _env("BOT_EMAIL")
    password = password or _env("BOT_PASSWORD")
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    try:
        r = requests.post(url, json={"email": email, "password": password, "returnSecureToken": True}, timeout=TIMEOUT)
    except requests.RequestException as ex:
        raise RuntimeError(f"Firebase sign-in network error: {ex}")
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not r.ok or "idToken" not in body:
        msg = (body.get("error") or {}).get("message", f"HTTP {r.status_code}")
        raise RuntimeError(f"Firebase sign-in failed: {msg}")
    return body["idToken"]


def read_existing(db_url=None, id_token=None):
    """Read cms/dailydeals (public read — no auth needed). Returns dict (may be {})."""
    db_url = (db_url or _env("FIREBASE_DB_URL")).rstrip("/")
    # Public read by design; auth optional.
    url = f"{db_url}/cms/dailydeals.json"
    params = {"auth": id_token} if id_token else None
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json() or {}


def push(db_url, id_token, item):
    """POST one deal item to cms/dailydeals. Returns the new Firebase key. Raises on error."""
    db_url = db_url.rstrip("/")
    r = requests.post(
        f"{db_url}/cms/dailydeals.json",
        params={"auth": id_token},
        json=item,
        timeout=TIMEOUT,
    )
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not r.ok or "name" not in body:
        msg = body.get("error", f"HTTP {r.status_code}")
        raise RuntimeError(f"Firebase push failed: {msg}")
    return body["name"]


def delete(db_url, id_token, key):
    """Delete one deal by Firebase key (used to clean up drafts if needed)."""
    db_url = db_url.rstrip("/")
    r = requests.delete(f"{db_url}/cms/dailydeals/{key}.json", params={"auth": id_token}, timeout=TIMEOUT)
    r.raise_for_status()
