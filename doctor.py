"""Comprehensive Doctor — validates projects and accounts; auto-corrects small
user mistakes (typos, whitespace, full URLs, wrong-case enums) and runs live
OAuth token checks.

Results are plain dicts:
    {
        "section": "Project",
        "label":   "YouTube Client ID",
        "ok":      bool,
        "note":    "human explanation",
        "fix":     (kind, key, value, desc) | None
    }
fix kinds:
    "field"          -> supabase_db.update_project(project_id, key=value)
    "account"        -> supabase_db.verify_account(key, status=value)
    "project_account"-> supabase_db.set_project_account(project_id, value)
"""

import difflib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import config
import supabase_db

PROVIDERS = ("vplink", "cleanuri", "tinyurl")
COMMENT_MODES = ("heldForReview", "published")

ACC = "YouTube Account"
PRJ = "Project"
CFG = "Settings"


# ─── Small-mistake correctors ────────────────────────────────────────────────

def _clean(value):
    if value is None:
        return ""
    return str(value).strip()


def fuzzy(value, choices):
    """Return the canonical choice matching a possibly-mistyped value, else None."""
    v = _clean(value).lower()
    if not v:
        return None
    norm = re.sub(r"[^a-z0-9]", "", v)
    for c in choices:
        if v == c:
            return c
        if norm and norm == re.sub(r"[^a-z0-9]", "", c):
            return c
    for c in choices:
        if c in v or v in c:
            return c
    for c in choices:
        if difflib.get_close_matches(v, [c], n=1, cutoff=0.6):
            return c
    return None


def sanitize_client_id(value):
    v = _clean(value)
    if not v:
        return v
    m = re.search(r"([\w\-]+\.apps\.googleusercontent\.com)", v)
    if m:
        return m.group(1)
    v = re.sub(r"^https?://", "", v).split("/")[0]
    v = v.split("?")[0]
    return v


# ─── Live checks ─────────────────────────────────────────────────────────────

def test_refresh_token(client_id, client_secret, refresh_token):
    """Returns (ok, note, expired_bool). Live OAuth token refresh test."""
    if not (client_id and client_secret and refresh_token):
        return False, "missing credentials", False
    try:
        data = urllib.parse.urlencode({
            "client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token",
                                     data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read())
            if tokens.get("access_token"):
                return True, "refresh OK", False
            return False, "no access_token returned", False
    except urllib.error.HTTPError as e:
        if e.code == 400:
            return False, "expired/invalid", True
        return False, f"HTTP {e.code}", False
    except Exception as e:
        return False, str(e)[:60], False


def test_proxy(proxy_url, timeout=15):
    """Returns (ok, latency_seconds, note). Live HTTPS request through the
    proxy to prove it can route traffic. Any HTTP status < 500 counts as a
    successful connection."""
    import time
    if not proxy_url:
        return False, 0.0, "no proxy URL given"
    try:
        import httplib2
        http = httplib2.Http(
            timeout=timeout,
            proxy_info=httplib2.proxy_info_from_url(proxy_url, "https"),
        )
        start = time.time()
        resp, _body = http.request("https://oauth2.googleapis.com/token", method="GET")
        latency = round(time.time() - start, 2)
        if resp.status < 500:
            return True, latency, f"reachable (HTTP {resp.status})"
        return False, latency, f"HTTP {resp.status}"
    except Exception as e:
        return False, 0.0, str(e)[:80]


def _fmt(ts):
    if not ts:
        return ""
    return str(ts)[:16].replace("T", " ")


# ─── Project checks ──────────────────────────────────────────────────────────

def check_project(project):
    checks = []

    def add(label, ok, note="", fix=None, section=PRJ):
        checks.append({"section": section, "label": label, "ok": ok,
                       "note": note, "fix": fix})

    cid = project.get("yt_client_id", "") or ""
    csec = project.get("yt_client_secret", "") or ""
    rt = project.get("yt_refresh_token", "") or ""
    account_id = project.get("account_id", "") or ""

    # ── Credentials ──
    cleaned = sanitize_client_id(cid)
    if cleaned and cleaned != cid:
        add("YouTube Client ID", False,
            fix=("field", "yt_client_id", cleaned, f"URL prefix stripped → {cleaned}"))
    elif cid:
        if ".apps.googleusercontent.com" not in cleaned:
            add("YouTube Client ID format", False,
                "should end with .apps.googleusercontent.com")
        else:
            add("YouTube Client ID", True)
    else:
        add("YouTube Client ID", False, "set your OAuth client ID")

    add("YouTube Client Secret", bool(csec), "" if csec else "set your OAuth client secret")

    ok_yt, yt_note, yt_expired = test_refresh_token(cleaned or cid, csec, rt)
    if ok_yt:
        add("YouTube Refresh Token", True, "valid — refresh OK")
    elif rt:
        suffix = " (re-run OAuth to get a fresh token)" if yt_expired else ""
        add("YouTube Refresh Token", False, yt_note + suffix)
    else:
        add("YouTube Refresh Token", False, "run OAuth login after setting client ID + secret")

    # ── Linked upload account ──
    if account_id:
        account = supabase_db.get_account(account_id)
        if not account:
            add("Linked upload account", False, f"'{account_id}' no longer exists",
                fix=("field", "account_id", "", f"unlinked missing account '{account_id}'"))
        else:
            a_ok, a_note, a_exp = test_refresh_token(account.get("client_id", ""),
                                                     account.get("client_secret", ""),
                                                     account.get("refresh_token", ""))
            label = f"Upload account '{account_id}'"
            if a_ok:
                add(label, True, f"{account.get('channel_name') or account_id} — token OK")
            elif a_exp:
                add(label, False, "token expired — re-run OAuth",
                    fix=("account", account_id, "expired", "marked expired — re-run OAuth"))
            else:
                add(label, False, a_note,
                    fix=("account", account_id, "expired", "marked expired — re-run OAuth"))
    else:
        add("Linked upload account", True, "none linked — using inline project credentials")

    # ── Shortlink provider (fuzzy) ──
    provider = project.get("shortlink_provider", "") or ""
    canon = fuzzy(provider, PROVIDERS)
    if provider and canon and canon != provider:
        add("Shortlink provider", False, section=CFG,
            fix=("field", "shortlink_provider", canon, f"'{provider}' → {canon}"))
    elif provider and not canon:
        add("Shortlink provider", False,
            fix=("field", "shortlink_provider", "vplink", f"invalid '{provider}' → vplink"),
            section=CFG)
    else:
        add("Shortlink provider", True, canon or "default: vplink", section=CFG)
    if (canon or provider) == "vplink" and not project.get("shortlink_api_key"):
        add("Shortlink API key", False, "vplink requires an API key", section=CFG)
    else:
        add("Shortlink API key", True,
            "set" if project.get("shortlink_api_key") else "not needed", section=CFG)

    # ── Comment moderation (fuzzy) ──
    cm = project.get("comment_moderation", "") or ""
    cm_canon = fuzzy(cm, COMMENT_MODES)
    if cm and cm_canon and cm_canon != cm:
        add("Comment mode", False, section=CFG,
            fix=("field", "comment_moderation", cm_canon, f"'{cm}' → {cm_canon}"))
    elif cm and not cm_canon:
        add("Comment mode", False,
            fix=("field", "comment_moderation", "published", f"invalid '{cm}' → published"),
            section=CFG)
    else:
        add("Comment mode", True, cm_canon or "default: published", section=CFG)

    # ── Proxy (global Settings) ──
    proxy = config.get_proxy_settings()
    if _clean(proxy.get("proxy_enabled")) not in ("", "false", "False", False, "0", "off"):
        host = _clean(proxy.get("proxy_host"))
        if not host:
            add("Proxy", False, "enabled but no host set — configure it in Settings",
                section=CFG)
        else:
            url = config.get_proxy_url()
            ok, lat, note = test_proxy(url)
            if ok:
                add("Proxy", True, f"{config.mask_proxy_url(url)} — {note} ({lat}s)",
                    section=CFG)
            else:
                add("Proxy", False, f"{config.mask_proxy_url(url)} — {note}",
                    fix=("setting", "proxy_enabled", "false",
                         "proxy unreachable — disabled until fixed"),
                    section=CFG)
    else:
        add("Proxy", True, "off — direct connection (enable in Settings if YouTube blocks your IP)",
            section=CFG)

    # ── Proxy pool (global Settings) ──
    pool_on = _clean(proxy.get("proxy_pool_enabled")) not in ("", "false", "False", False, "0", "off")
    if not pool_on:
        add("Proxy pool", True, "off — fastest live proxy selection disabled",
            section=CFG)
    else:
        import proxy_pool
        if not proxy_pool.is_configured():
            add("Proxy pool", False, "enabled but URL/key missing — set them in Settings",
                section=CFG)
        else:
            try:
                summary = proxy_pool.pool_summary()
                if summary.get("configured"):
                    alive = summary.get("alive", 0)
                    active = summary.get("active")
                    if alive and active:
                        add("Proxy pool", True,
                            f"{alive} alive, active {active['ip']}:{active.get('port')} ({active.get('latency_ms')}ms)",
                            section=CFG)
                    elif alive:
                        add("Proxy pool", False,
                            f"{alive} alive but none active — run Settings → [P] Refresh & test pool",
                            section=CFG)
                    else:
                        add("Proxy pool", False,
                            f"{summary.get('total', 0)} proxies in pool, 0 alive — refresh the pool",
                            section=CFG)
                else:
                    add("Proxy pool", False, summary.get("message", "pool unreachable"),
                        section=CFG)
            except Exception as e:
                add("Proxy pool", False, str(e)[:80], section=CFG)

    return checks


# ─── Account checks ──────────────────────────────────────────────────────────

def check_account(account):
    checks = []
    name = account.get("name", "")
    cid = account.get("client_id", "") or ""
    csec = account.get("client_secret", "") or ""
    rt = account.get("refresh_token", "") or ""
    status = account.get("status", "active") or "active"

    def add(label, ok, note="", fix=None):
        checks.append({"section": ACC, "label": label, "ok": ok,
                       "note": note, "fix": fix})

    add(f"Account '{name}'", bool(name), "" if name else "missing name")
    add(f"'{name}' client ID", bool(cid), "" if cid else "missing client ID")
    add(f"'{name}' client secret", bool(csec), "" if csec else "missing client secret")
    add(f"'{name}' refresh token", bool(rt), "" if rt else "missing refresh token")

    if cid and csec and rt:
        ok, note, expired = test_refresh_token(cid, csec, rt)
        if ok:
            add(f"'{name}' token", True, "valid — refresh OK",
                fix=("account", name, "active", "token verified"))
        elif expired:
            add(f"'{name}' token", False, "expired — re-run OAuth",
                fix=("account", name, "expired", "marked expired"))
        else:
            add(f"'{name}' token", False, note,
                fix=("account", name, "expired", "marked expired"))
    elif status == "active" and (cid or csec or rt):
        add(f"'{name}' credentials", False, "incomplete — fill all three")

    # Stored expiry bookkeeping
    exp = account.get("token_expires_at")
    if exp:
        try:
            t = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if t < datetime.now(timezone.utc):
                add(f"'{name}' token expiry", False, f"past expiry {_fmt(exp)}",
                    fix=("account", name, "expired", "marked expired"))
        except Exception:
            pass

    return checks


def check_accounts(accounts):
    checks = []
    for account in accounts:
        checks.extend(check_account(account))
    return checks


# ─── Apply fixes ─────────────────────────────────────────────────────────────

def apply_fixes(project_id, checks):
    """Apply every auto-fix from a set of checks. Returns number applied.
    project_id may be '' for account-only checks."""
    applied = 0
    failures = []
    for c in checks:
        if c.get("ok") or not c.get("fix"):
            continue
        kind, key, value, _desc = c["fix"]
        try:
            if kind == "field":
                supabase_db.update_project(project_id, **{key: value})
            elif kind == "account":
                supabase_db.verify_account(key, status=value)
            elif kind == "project_account":
                supabase_db.set_project_account(project_id, value)
            elif kind == "setting":
                supabase_db.set_setting(key, value)
            applied += 1
        except Exception as e:
            failures.append(f"{key}: {e}")
    return applied, failures


def summarize(checks):
    oks = sum(1 for c in checks if c["ok"])
    issues = sum(1 for c in checks if not c["ok"] and not c.get("fix"))
    fixes = sum(1 for c in checks if not c["ok"] and c.get("fix"))
    return oks, issues, fixes
