#!/usr/bin/env python3
"""cloud_bootstrap.py — one-shot cloud seeding + device bootstrap for
YT VIDEO AUTOMATION.

Purpose: the database is the single source of truth. Run this once (or on any
new device) and every credential/setting lands in the Supabase database as
JSON rows, so the TUI/CLI shows the latest data no matter which machine you
connect from.

Inputs (env vars, never hardcoded here):
    SUPABASE_URL / SUPABASE_SERVICE_KEY   main database (required)
    PROXY_POOL_URL / PROXY_POOL_KEY       proxy pool database (optional)
    YT_CLIENT_ID / YT_CLIENT_SECRET       Google OAuth client (optional)

What it does:
    1. connects to the main database (REST, like the app does)
    2. verifies the app tables exist (warns if schema.sql was not applied)
    3. seeds any MISSING rows (never overwrites existing data):
         settings.proxy_pool_url / proxy_pool_key        (JSON strings)
         settings.supabase_connection                    (JSON object)
         settings.google_oauth                           (JSON object)
         accounts."Main Channel"  (client_id/secret)     (row, no token yet)
    4. writes the local bootstrap (~/.yt-mirror/config.json) so the TUI and
       CLI on THIS machine connect to the cloud database automatically
    5. prints a summary of what is stored

Re-run it on any device after a fresh install — existing rows are left
untouched, only missing ones are created.
"""
import json
import os
import sys
from pathlib import Path

DATA_DIR = Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror")))
BOOTSTRAP = DATA_DIR / "config.json"

REQUIRED_TABLES = ("projects", "accounts", "settings", "upload_state",
                   "upload_logs", "verify_checks", "alerts")


def _env(*names):
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return ""


def _request(url, key, method, path, data=None):
    import urllib.error
    import urllib.request
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        f"{url.rstrip('/')}/rest/v1/{path.lstrip('/')}", data=body, method=method,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation,resolution=merge-duplicates",
        })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path}: HTTP {e.code} {e.read()[:200]!r}")


def main():
    url = _env("SUPABASE_URL")
    key = _env("SUPABASE_SERVICE_KEY", "SUPABASE_SECRET_KEY")
    if not url or not key:
        print("error: SUPABASE_URL + SUPABASE_SERVICE_KEY env vars are required")
        return 1

    print(f"connecting: {url}")

    # 1) tables exist?
    for t in REQUIRED_TABLES:
        try:
            _request(url, key, "GET", f"{t}?select=*&limit=1")
        except RuntimeError as e:
            if "404" in str(e):
                print(f"  WARN: table '{t}' missing — run schema.sql in the "
                      f"Supabase SQL editor first")
            else:
                print(f"  WARN: could not probe '{t}': {e}")

    # 2) settings (JSONB) — only missing keys
    existing = _request(url, key, "GET", "settings?select=key") or []
    have = {r.get("key") for r in existing}
    seeds = {}

    pool_url = _env("PROXY_POOL_URL")
    pool_key = _env("PROXY_POOL_KEY")
    if pool_url and pool_key:
        seeds["proxy_pool_url"] = pool_url
        seeds["proxy_pool_key"] = pool_key

    seeds["supabase_connection"] = {"url": url, "key": key}

    cid = _env("YT_CLIENT_ID")
    csec = _env("YT_CLIENT_SECRET")
    if cid and csec:
        seeds["google_oauth"] = {"client_id": cid, "client_secret": csec}

    for k, v in seeds.items():
        if k in have:
            print(f"  settings.{k}          — already present (kept)")
            continue
        _request(url, key, "POST", "settings?on_conflict=key",
                 data={"key": k, "value": json.dumps(v)})
        print(f"  settings.{k}          — seeded")

    # 3) account row (Google OAuth client; refresh token is added the first
    #    time you sign in with Google from any device, then syncs everywhere)
    accounts = _request(url, key, "GET", "accounts?select=name") or []
    if accounts:
        print(f"  accounts              — {len(accounts)} existing row(s) (kept)")
    elif cid and csec:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        _request(url, key, "POST", "accounts?on_conflict=name", data={
            "name": "Main Channel",
            "client_id": cid,
            "client_secret": csec,
            "refresh_token": "",
            "status": "active",
            "uploads_count": 0,
            "notes": "Seeded by cloud_bootstrap.py — run Google sign-in once to add the refresh token",
            "added_at": now,
            "created_at": now,
            "updated_at": now,
        })
        print("  accounts              — 'Main Channel' seeded (client id/secret; "
              "refresh token after first Google sign-in)")
    else:
        print("  accounts              — none (set YT_CLIENT_ID/YT_CLIENT_SECRET to seed)")

    # 4) local bootstrap so this machine's TUI/CLI auto-connect
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        DATA_DIR.chmod(0o700)
    except Exception:
        pass
    existing_cfg = {}
    try:
        existing_cfg = json.loads(BOOTSTRAP.read_text("utf-8"))
    except Exception:
        pass
    existing_cfg["supabase_url"] = url
    existing_cfg["supabase_key"] = key
    fd, tmp = __import__("tempfile").mkstemp(dir=str(DATA_DIR), prefix="config.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(existing_cfg, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, BOOTSTRAP)
    print(f"  bootstrap              — ~/.yt-mirror/config.json written (this device now cloud)")

    # 5) summary
    print("\nstored in the database (visible from every device):")
    rows = _request(url, key, "GET", "settings?select=key") or []
    for r in rows:
        print(f"  settings.{r.get('key')}")
    for a in _request(url, key, "GET", "accounts?select=name") or []:
        print(f"  accounts.{a.get('name')}")
    print("\ndone — on any other device, install, then run:")
    print("  SUPABASE_URL=<url> SUPABASE_SERVICE_KEY=<key> python3 cloud_bootstrap.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())