#!/usr/bin/env python3
"""YT VIDEO AUTOMATION — management TUI (hybrid: local JSON or Supabase).

Systematic menu layout
    MAIN
    ├─ Projects                manage upload projects (configure, status…)
    ├─ YouTube Accounts        every saved upload account + selection system
    ├─ Doctor                  full-system check with auto-correction
    ├─ Database connection     local JSON ⇄ Supabase
    └─ Settings                proxy & network (route uploads/downloads)
"""

import json, os, sys, time, http.server, urllib.request, urllib.error, urllib.parse, re, shutil
from pathlib import Path
from datetime import datetime, timezone

# The TUI renders box-drawing and symbol glyphs (╔═║╚╝ ✓ ✗ ⚠ ▸). Force UTF-8
# output so it never crashes with UnicodeEncodeError on non-UTF-8 consoles
# (e.g. Windows cp1252); replace unrenderable glyphs instead of dying.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    HAS_GAPI = True
except ImportError:
    HAS_GAPI = False

import config
import supabase_db
import youtube_api
import daily_uploader
import download_helpers
import verify_state
import doctor

DATA_DIR = Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror")))
BOOTSTRAP_PATH = DATA_DIR / "config.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube",
]

C_RESET  = "\033[0m"
C_BOLD   = "\033[1m"
C_DIM    = "\033[2m"
C_RED    = "\033[31m"
C_GREEN  = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE   = "\033[34m"
C_CYAN   = "\033[36m"
C_GRAY   = "\033[90m"
C_BOLDWHITE = "\033[1;37m"

# ─── Bootstrap ────────────────────────────────────────────────────────────────

def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path):
    _ensure_dir()
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return {}


def _write_json(path, data):
    _ensure_dir()
    import tempfile as _tf
    fd, tmp = _tf.mkstemp(dir=str(DATA_DIR), prefix=f"{Path(path).name}.", suffix=".tmp")
    try:
        os.write(fd, json.dumps(data, indent=2).encode("utf-8"))
        os.close(fd)
        os.chmod(tmp, 0o600)
        os.rename(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _is_true(v):
    return str(v).strip().lower() in ("true", "1", "yes", "on")


# ─── UI Helpers ───────────────────────────────────────────────────────────────

def clear():
    os.system("clear" if os.name != "nt" else "cls")


def banner():
    mode = "local JSON" if not supabase_db.is_enabled() else "supabase (cloud)"
    title = f"YT VIDEO AUTOMATION  ·  v{config.VERSION}  ·  {mode}"
    box = "═" * (len(title) + 4)
    print(f"""
{C_CYAN}{C_BOLD}╔{box}╗
║  {title}  ║
╚{box}╝{C_RESET}""")


def divider():
    print(f"  {C_DIM}{'─' * 56}{C_RESET}")


def prompt(msg, default=None):
    suffix = f" [{default}]" if default else ""
    val = input(f"  {C_CYAN}▸{C_RESET} {msg}{suffix}: ").strip()
    return val if val else (default or "")


def confirm(msg, default_no=True):
    key = "y/N" if default_no else "Y/n"
    val = input(f"  {C_YELLOW}?{C_RESET} {msg} ({key}): ").strip().lower()
    if not val:
        return not default_no
    return val in ("y", "yes")


def success(msg):
    print(f"  {C_GREEN}✓ {msg}{C_RESET}")


def error(msg):
    print(f"  {C_RED}✗ {msg}{C_RESET}")


def info(msg):
    print(f"  {C_BLUE}ℹ {msg}{C_RESET}")


def warn(msg):
    print(f"  {C_YELLOW}⚠ {msg}{C_RESET}")


def loading(msg):
    print(f"  {C_DIM}⏳ {msg}...{C_RESET}")


def pause():
    input("\n  Press Enter to continue...")


def _auto(v):
    """Mark an auto-corrected value in a prompt hint."""
    return f" {C_GREEN}(auto-corrected){C_RESET}" if v else ""


# ─── YouTube helpers ──────────────────────────────────────────────────────────

def _fetch_youtube_channel_info(refresh_token, client_id, client_secret):
    """Returns (channel_id, channel_name, avatar_url) or (None, None, '')."""
    if not HAS_GAPI:
        return None, None, ""
    try:
        yt = youtube_api.get_client(client_id, client_secret, refresh_token)
        resp = yt.channels().list(part="id,snippet", mine=True).execute()
        items = resp.get("items", [])
        if items:
            sn = items[0]["snippet"]
            avatar = sn.get("thumbnails", {}).get("default", {}).get("url", "")
            return items[0]["id"], sn.get("title", ""), avatar
    except Exception:
        pass
    return None, None, ""


# ─── Account store (hybrid: cloud accounts table / local accounts.json) ──────

def _accounts_dict():
    if supabase_db.is_enabled():
        return {r["name"]: r for r in supabase_db.get_all_accounts()}
    return config.load_accounts()


def _save_account(name, data):
    if supabase_db.is_enabled():
        supabase_db.save_account(name, dict(data))
    else:
        accounts = config.load_accounts()
        accounts[name] = dict(data)
        config.save_accounts(accounts)


def _delete_account(name):
    if supabase_db.is_enabled():
        supabase_db.delete_account(name)
    else:
        accounts = config.load_accounts()
        accounts.pop(name, None)
        config.save_accounts(accounts)


def _account_status_str(acct):
    status = acct.get("status", "active") or "active"
    if status == "active":
        sc = C_GREEN
    elif status == "expired":
        sc = C_RED
    else:
        sc = C_YELLOW
    lv = acct.get("last_verified", "")
    when = ""
    if lv:
        try:
            t = datetime.fromisoformat(str(lv).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            mins = int((datetime.now(timezone.utc) - t).total_seconds() // 60)
            if mins < 60:
                when = f", verified {mins}m ago"
            else:
                when = f", verified {mins // 60}h ago"
        except Exception:
            pass
    up = int(acct.get("uploads_count", 0) or 0)
    return f"{sc}{status}{C_RESET}{when}, {up} upload(s)"


def _resolve_client_creds():
    """Find reusable OAuth client ID/secret: existing account → config → env."""
    accounts = _accounts_dict()
    for acct in accounts.values():
        if acct.get("client_id") and acct.get("client_secret"):
            return acct["client_id"], acct["client_secret"]
    cfg = config.load()
    if cfg.get("yt_client_id") and cfg.get("yt_client_secret"):
        return cfg["yt_client_id"], cfg["yt_client_secret"]
    cid = os.environ.get("YT_CLIENT_ID", "")
    csec = os.environ.get("YT_CLIENT_SECRET", "")
    if cid and csec:
        return cid, csec
    return "", ""


# ─── OAuth flow (shared by accounts + project setup) ─────────────────────────

def _run_oauth_flow(client_id, client_secret):
    import hashlib, base64 as b64

    client_id = config.sanitize_client_id(client_id)

    if not client_id or not client_secret:
        error("Client ID and Secret are required first")
        return None

    config.apply_proxy_env()

    code_verifier = b64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    code_challenge = b64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()

    scopes = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/youtube"
    params = {
        "client_id": client_id,
        "redirect_uri": "http://127.0.0.1:8085",
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(params)

    result = {"code": None}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            code = qs.get("code", [None])[0]
            if code:
                result["code"] = code
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h2>Done! Close this tab.</h2></body></html>")
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    print()
    info("Starting local server on port 8085...")
    try:
        server = http.server.HTTPServer(("0.0.0.0", 8085), Handler)
    except OSError:
        error("Port 8085 in use — try again or wait")
        return None
    server.timeout = 300

    print()
    print(f"  {C_BOLD}Open this URL in your browser and authorize:{C_RESET}")
    print(f"  {auth_url}")
    print()
    info("Waiting for callback (300s timeout)...")

    server.handle_request()
    server.server_close()

    if not result["code"]:
        error("OAuth timed out or no code received")
        return None

    token_data = urllib.parse.urlencode({
        "code": result["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": "http://127.0.0.1:8085",
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }).encode()
    try:
        req = urllib.request.Request("https://oauth2.googleapis.com/token",
                                     data=token_data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=30) as resp:
            tokens = json.loads(resp.read())
            rt = tokens.get("refresh_token", "")
            if rt:
                return rt
            error("No refresh token returned — make sure the OAuth consent screen is Published")
            return None
    except Exception as e:
        error(f"Token exchange failed: {e}")
        return None


# ─── Local-mode sync (hybrid DB) ──────────────────────────────────────────────

def _local_settings_path():
    return DATA_DIR / "settings.json"


def _sync_local_project(p):
    """Local mode: mirror a project's fields onto the files the local tool
    reads (settings.json, config.json)."""
    if supabase_db.is_enabled() or not p:
        return
    settings = {}
    try:
        settings = json.loads(_local_settings_path().read_text("utf-8"))
    except Exception:
        pass
    for k in ("comment_moderation", "mirror_title_prefix",
              "custom_title", "custom_description", "custom_comment"):
        if k in p and p[k] not in (None, ""):
            settings[k] = p[k]
    settings["shortlink_provider"] = p.get("shortlink_provider") or "none"
    if p.get("shortlink_api_key"):
        settings["shortlink_api_key"] = p["shortlink_api_key"]
    settings["active_account"] = p.get("account_id") or ""
    _write_json(_local_settings_path(), settings)

    patch = {}
    for k in ("yt_client_id", "yt_client_secret", "yt_refresh_token"):
        if p.get(k):
            patch[k] = p[k]
    if patch:
        config.save(patch)


# ─── MAIN MENU ────────────────────────────────────────────────────────────────

def _proxy_status_str():
    s = config.get_proxy_settings()
    if not _is_true(s.get("proxy_enabled")):
        return f"{C_DIM}proxy: off{C_RESET}"
    host = str(s.get("proxy_host", "") or "").strip()
    if not host:
        return f"{C_YELLOW}proxy: enabled, missing host{C_RESET}"
    return f"{C_GREEN}proxy: {host}{C_RESET}"


def _print_quick_status():
    try:
        status = daily_uploader.get_status()
    except Exception:
        status = {"total_uploaded": 0}
    if config.is_configured():
        cred = C_GREEN
        cred_str = "OK"
    else:
        cred = C_RED
        cred_str = "MISSING"
    print(f"  {C_DIM}YouTube login:{C_RESET} {cred}{cred_str}{C_RESET}"
          f"   {_proxy_status_str()}"
          f"   {C_DIM}uploads:{C_RESET} {status.get('total_uploaded', 0)}")


def main_menu():
    while True:
        clear()
        banner()
        print()
        _print_quick_status()
        print(f"\n  {C_BOLDWHITE}MAIN MENU{C_RESET}")
        divider()
        print(f"  {C_BOLD}[Q]{C_RESET} Quick Deploy — guided questions → process → upload")
        print(f"  {C_BOLD}[1]{C_RESET} Projects — pick a project & upload a video")
        print(f"  {C_BOLD}[2]{C_RESET} YouTube Accounts — saved channel logins")
        print(f"  {C_BOLD}[3]{C_RESET} Doctor — full system check & auto-fix")
        print(f"  {C_BOLD}[4]{C_RESET} Database — local JSON ⇄ Supabase cloud")
        print(f"  {C_BOLD}[5]{C_RESET} Settings — proxy, network & defaults")
        print(f"  {C_BOLD}[0]{C_RESET} Quit")
        print()
        if supabase_db.is_enabled():
            connected_to = _read_json(BOOTSTRAP_PATH).get("supabase_url", "")
            print(f"  {C_DIM}Database: Supabase (cloud){C_RESET}" + (f"  —  {connected_to}" if connected_to else ""))
        else:
            print(f"  {C_DIM}Database: local JSON — data in {DATA_DIR}{C_RESET}")
        print()

        choice = prompt("Choice").strip().upper()
        if choice == "0":
            print(f"\n  {C_DIM}Bye!{C_RESET}\n")
            break
        elif choice == "Q":
            quick_deploy_screen()
        elif choice == "1":
            project_list_screen()
        elif choice == "2":
            accounts_screen()
        elif choice == "3":
            screen_doctor()
        elif choice == "4":
            _database_screen()
        elif choice == "5":
            settings_screen()


def _database_screen():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}DATABASE CONNECTION{C_RESET}")
        divider()
        if supabase_db.is_enabled():
            su = _read_json(BOOTSTRAP_PATH).get("supabase_url", "")
            print(f"  {C_GREEN}Supabase connected:{C_RESET} {su}")
            print()
            print(f"  {C_BOLD}[1]{C_RESET} Disconnect → switch to LOCAL mode")
        else:
            print(f"  {C_DIM}Local JSON mode — data stored in {DATA_DIR}{C_RESET}")
            print()
            print(f"  {C_BOLD}[1]{C_RESET} Connect Supabase (cloud)")
        print(f"  {C_BOLD}[0]{C_RESET} Back")
        print()

        choice = prompt("Choice").strip().upper()
        if choice == "0":
            return
        elif choice == "1":
            if supabase_db.is_enabled():
                if confirm("Disconnect from Supabase and switch to LOCAL mode?"):
                    supabase_db.disable()
                    _write_json(BOOTSTRAP_PATH, {})
                    success("Local mode — data now stored in ~/.yt-mirror/")
                    pause()
            else:
                su = prompt("Supabase URL", _read_json(BOOTSTRAP_PATH).get("supabase_url", ""))
                sk = prompt("Supabase Service Key", _read_json(BOOTSTRAP_PATH).get("supabase_key", ""))
                if su and sk:
                    _write_json(BOOTSTRAP_PATH, {"supabase_url": su, "supabase_key": sk})
                    supabase_db.configure(su, sk)
                    if supabase_db.is_enabled():
                        success("Connected to Supabase — cloud mode")
                    else:
                        error("Connection failed — check URL and key")
                    pause()


# ─── SETTINGS (proxy & network) ──────────────────────────────────────────────

PROXY_TYPES = ("http", "https", "socks4", "socks5")


def _masked_display(val):
    if not val:
        return f"{C_DIM}(empty){C_RESET}"
    return "*" * 6 + str(val)[-4:]


def _toggle_proxy(current):
    if current:
        config.save_proxy_settings(proxy_enabled=False)
        success("Proxy disabled — direct connection")
    else:
        host = str(config.get_proxy_settings().get("proxy_host", "") or "").strip()
        if not host:
            warn("Set Host and Port first — proxy stays disabled")
            pause()
            return
        config.save_proxy_settings(proxy_enabled=True)
        success("Proxy enabled — uploads & downloads now go through it")
    pause()


def _set_proxy_type(current):
    new = prompt("Proxy type (http/https/socks4/socks5)", current)
    if new:
        canon = doctor.fuzzy(new, PROXY_TYPES)
        if not canon:
            error(f"Use one of {', '.join(PROXY_TYPES)}")
        else:
            config.save_proxy_settings(proxy_protocol=canon)
            success(f"Proxy type set to {canon}")
    pause()


def _set_proxy_host(current):
    new = prompt("Proxy host (IP or hostname)", current or None)
    if new is None:
        return
    new = new.strip()
    if new and any(ch.isspace() or ch in "?\"'\\" for ch in new):
        error("Host looks invalid — use an IP address or hostname")
        pause()
        return
    config.save_proxy_settings(proxy_host=new)
    success("Proxy host saved" + ("" if new else " (cleared)"))
    pause()


def _set_proxy_port(current):
    new = prompt("Proxy port (e.g. 3128, 8080, 1080)", current or None)
    if new is None:
        return
    new = new.strip()
    if new and not new.isdigit():
        error("Port must be a number")
        pause()
        return
    if new and not 1 <= int(new) <= 65535:
        error("Port out of range (1–65535)")
        pause()
        return
    config.save_proxy_settings(proxy_port=new)
    success("Proxy port saved" + ("" if new else " (cleared)"))
    pause()


def _set_proxy_user(current):
    new = prompt("Proxy username (optional)", current or None)
    if new is None:
        return
    config.save_proxy_settings(proxy_username=new.strip())
    success("Proxy username saved" + ("" if new.strip() else " (cleared)"))
    pause()


def _set_proxy_password(current):
    new = prompt("Proxy password (optional)", current or None)
    if new is None:
        return
    config.save_proxy_settings(proxy_password=new.strip())
    success("Proxy password saved" + ("" if new.strip() else " (cleared)"))
    pause()


def _test_proxy_now():
    url = config.get_proxy_url()
    if not url:
        warn("Proxy not configured — set Host and Port, then enable it")
        pause()
        return
    loading(f"Testing {config.mask_proxy_url(url)}...")
    ok, latency, note = doctor.test_proxy(url)
    if ok:
        success(f"Proxy works — reachable in {latency}s ({note})")
    else:
        error(f"Proxy failed — {note}")
    pause()


def _clear_proxy():
    if not confirm("Clear all proxy settings?"):
        return
    config.save_proxy_settings(
        proxy_enabled=False, proxy_protocol="http",
        proxy_host="", proxy_port="", proxy_username="", proxy_password="")
    success("Proxy settings cleared — running direct")
    pause()


def _toggle_pool(enabled):
    if enabled:
        config.save_proxy_settings(proxy_pool_enabled=False)
        success("Proxy pool disabled — using manual proxy/direct")
    else:
        import proxy_pool
        if not proxy_pool.is_configured():
            warn("Set Pool URL and Pool Key first — pool stays disabled")
            pause()
            return
        config.save_proxy_settings(proxy_pool_enabled=True)
        success("Proxy pool enabled — fastest live proxy auto-activated")
    pause()


def _set_pool_url(current):
    new = prompt("Pool Supabase URL (https://...supabase.co)", current or None)
    if new is None:
        return
    config.save_proxy_settings(proxy_pool_url=new.strip())
    success("Pool URL saved" + ("" if new.strip() else " (cleared)"))
    pause()


def _set_pool_key(current):
    new = prompt("Pool Supabase key (service key)", current or None)
    if new is None:
        return
    config.save_proxy_settings(proxy_pool_key=new.strip())
    success("Pool key saved" + ("" if new.strip() else " (cleared)"))
    pause()


def _set_processing_num(key, label, current, minimum=0):
    new = prompt(f"{label} (current {current})").strip()
    if not new:
        return
    try:
        value = int(float(new))
    except ValueError:
        error("Must be a number")
        pause()
        return
    if value < minimum:
        error(f"Must be at least {minimum}")
        pause()
        return
    config.save_tui_setting(key, value)
    success(f"{label} set to {value}")
    pause()


def _set_bgm_source(current):
    print(f"\n  {C_DIM}BGM source options:{C_RESET}")
    print(f"    {C_BOLD}none{C_RESET}     — vocals-only, nothing mixed in (100% safe)")
    print(f"    {C_BOLD}yt_link{C_RESET}  — download audio from your copyright-free YouTube link")
    print(f"    {C_BOLD}builtin{C_RESET}  — builtin royalty-free library")
    print(f"    {C_BOLD}local{C_RESET}    — files from your own royalty-free folder")
    new = prompt("BGM source", current).strip().lower()
    if new not in ("none", "yt_link", "builtin", "local"):
        error("Invalid BGM source")
        pause()
        return
    config.save_tui_setting("bgm_source", new)
    success(f"BGM source set to '{new}'")
    pause()


def _pool_refresh_now():
    import proxy_pool
    if not proxy_pool.is_configured():
        warn("Proxy pool not configured — set Pool URL and Pool Key first")
        pause()
        return
    loading("Refreshing & testing proxy pool (this takes a minute)...")

    def progress(done, total, ip):
        print(f"  {C_DIM}   tested {done}/{total} — {ip}{C_RESET}", end="\r")

    best, msg = proxy_pool.refresh_and_activate(progress=progress)
    print()
    if best:
        success(msg)
    else:
        error(msg)
    pause()


def _pool_status_now():
    import proxy_pool
    summary = proxy_pool.pool_summary()
    if not summary.get("configured"):
        warn(summary.get("message", "pool not configured"))
        pause()
        return
    print()
    print(f"  {C_BOLDWHITE}PROXY POOL STATUS{C_RESET}")
    divider()
    print(f"  Total proxies in pool:  {summary.get('total', 0)}")
    print(f"  Alive after last test:   {summary.get('alive', 0)}")
    best = summary.get("best")
    if best:
        print(f"  Fastest live proxy:      {best['ip']}:{best.get('port')} ({best.get('latency_ms')}ms)")
    else:
        print(f"  Fastest live proxy:      {C_DIM}none working{C_RESET}")
    active = summary.get("active")
    if active:
        print(f"  Currently active:        {active['ip']}:{active.get('port')} ({active.get('latency_ms')}ms)")
    else:
        print(f"  Currently active:        {C_DIM}none (not pooled){C_RESET}")
    print()
    pause()


def settings_screen():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}SETTINGS{C_RESET}")
        divider()
        print(f"\n  {C_BOLDWHITE}NETWORK / PROXY{C_RESET}")
        print(f"  {C_DIM}Route downloads and YouTube uploads through a proxy — use this{C_RESET}")
        print(f"  {C_DIM}when YouTube blocks publishing from your server (data centre) IP.{C_RESET}")
        divider()
        s = config.get_proxy_settings()
        enabled = _is_true(s.get("proxy_enabled"))
        proto = str(s.get("proxy_protocol") or "http").strip() or "http"
        host = str(s.get("proxy_host") or "").strip()
        port = str(s.get("proxy_port") or "").strip()
        user = str(s.get("proxy_username") or "").strip()
        pwd = str(s.get("proxy_password") or "").strip()
        url = config.get_proxy_url()

        on = C_GREEN if enabled else C_DIM
        label = "ON" if enabled else "OFF"
        print(f"  {C_BOLD}[1]{C_RESET} Enable proxy       {on}{label}{C_RESET}")
        print(f"  {C_BOLD}[2]{C_RESET} Proxy type         {proto}")
        print(f"  {C_BOLD}[3]{C_RESET} Host               {host or f'{C_DIM}(empty){C_RESET}'}")
        print(f"  {C_BOLD}[4]{C_RESET} Port               {port or f'{C_DIM}(empty){C_RESET}'}")
        print(f"  {C_BOLD}[5]{C_RESET} Username (opt.)    {user or f'{C_DIM}(empty){C_RESET}'}")
        print(f"  {C_BOLD}[6]{C_RESET} Password (opt.)    {_masked_display(pwd) if pwd else f'{C_DIM}(empty){C_RESET}'}")
        if url:
            print(f"\n  {C_DIM}Current proxy: {C_RESET}{config.mask_proxy_url(url)}")
        print()
        print(f"  {C_BOLD}[T]{C_RESET} Test proxy — live connection check")
        print(f"  {C_BOLD}[X]{C_RESET} Clear proxy settings")
        print(f"  {C_BOLD}[0]{C_RESET} Back")
        print()
        divider()
        print(f"\n  {C_BOLDWHITE}PROXY POOL{C_RESET}")
        print(f"  {C_DIM}Reads the pool DB, re-tests dead proxies, picks the fastest live one{C_RESET}")
        print(f"  {C_DIM}and auto-swaps when the active proxy stops working.{C_RESET}")
        divider()
        pe = _is_true(s.get("proxy_pool_enabled"))
        pou = str(s.get("proxy_pool_url") or "").strip()
        pok = str(s.get("proxy_pool_key") or "").strip()
        pon = C_GREEN if pe else C_DIM
        plabel = "ON" if pe else "OFF"
        print(f"  {C_BOLD}[7]{C_RESET} Enable pool         {pon}{plabel}{C_RESET}")
        print(f"  {C_BOLD}[8]{C_RESET} Pool URL            {pou or f'{C_DIM}(empty){C_RESET}'}")
        print(f"  {C_BOLD}[9]{C_RESET} Pool key            {_masked_display(pok) if pok else f'{C_DIM}(empty){C_RESET}'}")
        print(f"  {C_BOLD}[P]{C_RESET} Refresh & test pool — then activate fastest")
        print(f"  {C_BOLD}[S]{C_RESET} Pool status")
        print()
        divider()
        print(f"\n  {C_BOLDWHITE}PROCESSING — copyright-safe BGM, fps & trim{C_RESET}")
        print(f"  {C_DIM}Frame rate, seconds cut from start/end, and where the{C_RESET}")
        print(f"  {C_DIM}non-copyright BGM comes from (your link, library, or none).{C_RESET}")
        divider()
        t = config.load_tui_settings()

        def _tnum(key, default):
            try:
                return int(float(t.get(key) or default))
            except (TypeError, ValueError):
                return default

        tfps = _tnum("fps", 20)
        tts = _tnum("trim_start", 20)
        tte = _tnum("trim_end", 10)
        tbsrc = str(t.get("bgm_source") or "yt_link")
        tburl = str(t.get("bgm_yt_url") or "").strip()
        tbdir = str(t.get("bgm_dir") or "").strip()
        print(f"  {C_BOLD}[A]{C_RESET} Frame rate           {tfps} fps")
        print(f"  {C_BOLD}[B]{C_RESET} Cut from start (s)   {tts}")
        print(f"  {C_BOLD}[C]{C_RESET} Cut from end (s)     {tte}")
        print(f"  {C_BOLD}[D]{C_RESET} BGM source           {tbsrc}  ({C_DIM}none | yt_link | builtin | local{C_RESET})")
        print(f"  {C_BOLD}[E]{C_RESET} Copyright-free YT link  {tburl or f'{C_DIM}(empty){C_RESET}'}")
        print(f"  {C_BOLD}[F]{C_RESET} Local BGM folder     {tbdir or f'{C_DIM}(empty){C_RESET}'}")
        print()

        choice = prompt("Choice").strip().upper()
        if choice == "0":
            return
        elif choice == "1":
            _toggle_proxy(enabled)
        elif choice == "2":
            _set_proxy_type(proto)
        elif choice == "3":
            _set_proxy_host(host)
        elif choice == "4":
            _set_proxy_port(port)
        elif choice == "5":
            _set_proxy_user(user)
        elif choice == "6":
            _set_proxy_password(pwd)
        elif choice == "7":
            _toggle_pool(pe)
        elif choice == "8":
            _set_pool_url(pou)
        elif choice == "9":
            _set_pool_key(pok)
        elif choice == "P":
            _pool_refresh_now()
        elif choice == "S":
            _pool_status_now()
        elif choice == "T":
            _test_proxy_now()
        elif choice == "X":
            _clear_proxy()
        elif choice == "A":
            _set_processing_num("fps", "Frame rate (fps)", tfps, minimum=1)
        elif choice == "B":
            _set_processing_num("trim_start", "Cut from start (seconds)", tts, minimum=0)
        elif choice == "C":
            _set_processing_num("trim_end", "Cut from end (seconds)", tte, minimum=0)
        elif choice == "D":
            _set_bgm_source(tbsrc)
        elif choice == "E":
            new_url = prompt("Copyright-free music YouTube link", tburl)
            config.save_tui_setting("bgm_yt_url", new_url.strip())
            success("Copyright-free BGM link saved")
        elif choice == "F":
            new_dir = prompt("Local BGM folder path", tbdir)
            config.save_tui_setting("bgm_dir", new_dir.strip())
            success("Local BGM folder saved")


# ─── YOUTUBE ACCOUNTS ─────────────────────────────────────────────────────────

def accounts_screen():
    while True:
        clear()
        banner()
        accounts = _accounts_dict()
        print(f"\n  {C_BOLDWHITE}YOUTUBE ACCOUNTS — {len(accounts)} saved{C_RESET}")
        divider()
        if not accounts:
            print(f"\n  {C_DIM}No accounts saved yet. Add your first one with [A].{C_RESET}")
        else:
            for i, (name, acct) in enumerate(accounts.items(), 1):
                ch = acct.get("channel_name", "") or acct.get("channel_id", "")
                ch_str = f" — {C_BOLD}{ch}{C_RESET}" if ch else ""
                print(f"  {C_BOLD}{i:2d}.{C_RESET} {name}{ch_str}")
                print(f"       {C_DIM}{_account_status_str(acct)}{C_RESET}")
        print()
        print(f"  {C_BOLD}[A]{C_RESET} Add account — OAuth login")
        print(f"  {C_BOLD}[M]{C_RESET} Add account — manually (paste credentials)")
        print(f"  {C_BOLD}[E]{C_RESET} Edit account")
        print(f"  {C_BOLD}[V]{C_RESET} Verify all accounts (live token test)")
        if accounts:
            print(f"  {C_BOLD}[D]{C_RESET} Delete account")
        print(f"  {C_BOLD}[0]{C_RESET} Back")
        print()

        choice = prompt("Choice").strip().upper()
        if choice == "0":
            return
        elif choice == "A":
            _add_account_oauth()
        elif choice == "M":
            _add_account_manual()
        elif choice == "E":
            _edit_account(accounts)
        elif choice == "V":
            _verify_all_accounts()
        elif choice == "D" and accounts:
            _delete_account_menu(accounts)


def _add_account_oauth():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}ADD YOUTUBE ACCOUNT (OAUTH){C_RESET}")
    divider()

    name = prompt("Account name (e.g. 'My Main Channel')")
    if not name:
        error("Name required")
        pause()
        return

    cid, csec = _resolve_client_creds()
    cid = config.sanitize_client_id(cid)
    if not cid:
        cid = config.sanitize_client_id(prompt("YouTube Client ID"))
    if not csec:
        csec = prompt("YouTube Client Secret")
    if not cid or not csec:
        error("Client ID and Secret are required for OAuth")
        pause()
        return

    print(f"\n  {C_DIM}Using Client ID: {cid}{C_RESET}")
    rt = _run_oauth_flow(cid, csec)
    if not rt:
        pause()
        return

    loading("Fetching channel info...")
    channel_id, channel_name, avatar = _fetch_youtube_channel_info(rt, cid, csec)
    _save_account(name, {
        "client_id": doctor.sanitize_client_id(cid),
        "client_secret": csec,
        "refresh_token": rt,
        "channel_id": channel_id or "",
        "channel_name": channel_name or "",
        "channel_url": f"https://www.youtube.com/channel/{channel_id}" if channel_id else "",
        "avatar_url": avatar or "",
        "status": "active",
        "last_verified": datetime.now(timezone.utc).isoformat(),
        "token_expires_at": (datetime.now(timezone.utc)).isoformat(),
        "uploads_count": 0,
        "notes": "",
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    success(f"Account '{name}' saved" + (f" — {channel_name}" if channel_name else ""))
    warn("Refresh tokens expire ~7 days — re-verify from the Accounts menu before then")

    if not supabase_db.is_enabled() and confirm("Set this as the active local account?"):
        settings = config.load_tui_settings()
        settings["active_account"] = name
        settings.pop("upload_settings", None)
        _write_json(_local_settings_path(), {k: v for k, v in settings.items()})
        success("Active account set")
    pause()


def _add_account_manual():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}ADD YOUTUBE ACCOUNT (MANUAL){C_RESET}")
    divider()

    name = prompt("Account name (e.g. 'My Main Channel')")
    if not name:
        error("Name required")
        pause()
        return
    cid = doctor.sanitize_client_id(prompt("YouTube Client ID"))
    csec = prompt("YouTube Client Secret")
    rt = prompt("YouTube Refresh Token")
    if not (cid and csec and rt):
        error("Client ID, Secret and Refresh Token are all required")
        pause()
        return
    channel_id = prompt("Channel ID (optional)")
    channel_name = prompt("Channel name (optional)")

    _save_account(name, {
        "client_id": cid,
        "client_secret": csec,
        "refresh_token": rt,
        "channel_id": channel_id or "",
        "channel_name": channel_name or "",
        "channel_url": f"https://www.youtube.com/channel/{channel_id}" if channel_id else "",
        "status": "active",
        "last_verified": "",
        "token_expires_at": "",
        "uploads_count": 0,
        "notes": "",
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    success(f"Account '{name}' saved")
    info("Run [V] Verify all accounts to test the token live")
    pause()


def _pick_account(accounts, verb="Select"):
    if not accounts:
        warn("No accounts saved — add one first")
        return None
    print()
    for i, (name, acct) in enumerate(accounts.items(), 1):
        ch = acct.get("channel_name", "") or acct.get("channel_id", "")
        ch_str = f" — {ch}" if ch else ""
        print(f"  {C_BOLD}{i:2d}.{C_RESET} {name}{ch_str}  {C_DIM}({_account_status_str(acct)}){C_RESET}")
    print()
    num = prompt(f"{verb} account number")
    if num and num.isdigit():
        idx = int(num) - 1
        if 0 <= idx < len(accounts):
            return list(accounts.keys())[idx]
    error("Invalid choice")
    return None


def _edit_account(accounts):
    if not accounts:
        warn("No accounts saved")
        pause()
        return
    name = _pick_account(accounts, "Edit")
    if not name:
        pause()
        return
    acct = dict(accounts[name])

    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}EDIT ACCOUNT — {name}{C_RESET}")
        divider()
        ch = acct.get("channel_name", "") or acct.get("channel_id", "")
        print(f"  {C_DIM}Channel:{C_RESET}  {ch or '(unknown)'}")
        print(f"  {C_DIM}Status:{C_RESET}   {_account_status_str(acct)}")
        print(f"  {C_DIM}Notes:{C_RESET}     {acct.get('notes', '') or '(none)'}")
        print()
        print(f"  {C_BOLD}[1]{C_RESET} Rename")
        print(f"  {C_BOLD}[2]{C_RESET} Client ID")
        print(f"  {C_BOLD}[3]{C_RESET} Client Secret")
        print(f"  {C_BOLD}[4]{C_RESET} Refresh Token")
        print(f"  {C_BOLD}[5]{C_RESET} Channel name / ID")
        print(f"  {C_BOLD}[6]{C_RESET} Notes")
        print(f"  {C_BOLD}[7]{C_RESET} Re-verify token (live test)")
        print(f"  {C_BOLD}[8]{C_RESET} OAuth re-login for this account")
        print(f"  {C_BOLD}[0]{C_RESET} Back")
        print()

        choice = prompt("Choice").strip().upper()
        if choice == "0":
            return
        elif choice == "1":
            new = prompt("New account name", name)
            if new and new != name:
                if new in accounts:
                    error("Name already exists")
                    continue
                _save_account(new, acct)
                _delete_account(name)
                _relink_projects(name, new)
                success(f"Renamed to '{new}'")
                name = new
        elif choice == "2":
            val = doctor.sanitize_client_id(prompt("Client ID", acct.get("client_id", "")))
            acct["client_id"] = val
            _save_account(name, acct)
            success("Client ID saved")
        elif choice == "3":
            val = prompt("Client Secret", acct.get("client_secret", ""))
            acct["client_secret"] = val
            _save_account(name, acct)
            success("Client Secret saved")
        elif choice == "4":
            val = prompt("Refresh Token", acct.get("refresh_token", ""))
            acct["refresh_token"] = val
            acct["status"] = "active"
            acct["last_verified"] = ""
            _save_account(name, acct)
            success("Refresh Token saved")
        elif choice == "5":
            ch_id = prompt("Channel ID", acct.get("channel_id", ""))
            ch_name = prompt("Channel name", acct.get("channel_name", ""))
            acct["channel_id"] = ch_id
            acct["channel_name"] = ch_name
            acct["channel_url"] = f"https://www.youtube.com/channel/{ch_id}" if ch_id else ""
            _save_account(name, acct)
            success("Channel info saved")
        elif choice == "6":
            val = prompt("Notes", acct.get("notes", ""))
            acct["notes"] = val
            _save_account(name, acct)
            success("Notes saved")
        elif choice == "7":
            _verify_one_account(name, acct, live=True)
            accounts[name] = acct
        elif choice == "8":
            rt = _run_oauth_flow(acct.get("client_id", ""), acct.get("client_secret", ""))
            if rt:
                acct["refresh_token"] = rt
                acct["status"] = "active"
                acct["last_verified"] = datetime.now(timezone.utc).isoformat()
                _save_account(name, acct)
                success("Refresh token refreshed")
            pause()


def _relink_projects(old_name, new_name):
    try:
        for p in supabase_db.list_projects():
            if p.get("account_id") == old_name:
                supabase_db.update_project(p["id"], account_id=new_name)
    except Exception as e:
        warn(f"Could not relink projects: {e}")


def _verify_one_account(name, acct, live=False):
    cid = acct.get("client_id", "")
    csec = acct.get("client_secret", "")
    rt = acct.get("refresh_token", "")
    ok, note, expired = doctor.test_refresh_token(cid, csec, rt)
    status = "active" if ok else ("expired" if expired else "expired")
    acct["status"] = status
    acct["last_verified"] = datetime.now(timezone.utc).isoformat() if ok else acct.get("last_verified", "")
    if ok:
        acct["token_expires_at"] = (datetime.now(timezone.utc)).isoformat()
        acct["last_error"] = ""
        print(f"  {C_GREEN}[OK]{C_RESET}   {name} — {note}")
    else:
        acct["last_error"] = note
        print(f"  {C_RED}[FAIL]{C_RESET} {name} — {note}")
    if live or not supabase_db.is_enabled():
        _save_account(name, acct)
    return ok


def _verify_all_accounts():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}VERIFY YOUTUBE ACCOUNTS{C_RESET}")
    divider()
    accounts = _accounts_dict()
    if not accounts:
        info("No accounts to verify")
        pause()
        return
    passed = 0
    for name, acct in accounts.items():
        if _verify_one_account(name, dict(acct), live=True):
            passed += 1
    print()
    success(f"{passed}/{len(accounts)} accounts verified")
    pause()


def _delete_account_menu(accounts):
    name = _pick_account(accounts, "Delete")
    if not name:
        pause()
        return
    if not confirm(f"Delete account '{name}' and unlink it from all projects?"):
        return
    _delete_account(name)
    for p in supabase_db.list_projects():
        if p.get("account_id") == name:
            supabase_db.update_project(p["id"], account_id="")
    success(f"Deleted '{name}'")
    pause()


# ─── PROJECTS ────────────────────────────────────────────────────────────────

def project_list_screen():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}PROJECTS{C_RESET}")
        divider()

        try:
            projects = supabase_db.list_projects()
        except Exception as e:
            error(f"Database unreachable: {str(e)[:60]}")
            if supabase_db.is_enabled():
                warn("Supabase connection failed — press [4] in main menu to fix")
            projects = None

        if not projects:
            print(f"\n  {C_DIM}No projects yet. Create one to get started.{C_RESET}")
        else:
            for i, p in enumerate(projects, 1):
                print(f"  {C_BOLD}{i:2d}.{C_RESET} {C_BOLD}{p['name']}{C_RESET}")
                parts = []
                for key, label in [("yt_client_id", "YT"), ("yt_client_secret", "YTS"),
                                    ("yt_refresh_token", "RT")]:
                    if p.get(key):
                        parts.append(label)
                if p.get("account_id"):
                    parts.append(f"acct:{p['account_id']}")
                if parts:
                    print(f"       {C_DIM}{', '.join(parts)}{C_RESET}")
            print()

        print(f"  {C_BOLD}[A]{C_RESET} Add project")
        if projects:
            print(f"  {C_BOLD}[D]{C_RESET} Delete project")
            print(f"  {C_BOLD}[1-{len(projects)}]{C_RESET} Select project")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice").strip().upper()
        if choice == "0":
            return
        elif choice == "A":
            name = prompt("Project name")
            if name:
                try:
                    p = supabase_db.create_project(name)
                    if p and p.get("id"):
                        success(f"Project '{name}' created")
                        if not supabase_db.is_enabled():
                            _sync_local_project(p)
                    else:
                        error("Failed to create project — name may already exist")
                except Exception as e:
                    msg = str(e)
                    if "409" in msg or "Conflict" in msg:
                        error("Project name already exists — choose a different name")
                    else:
                        error(f"Failed to create project: {e}")
        elif choice == "D" and projects:
            for i, p in enumerate(projects, 1):
                print(f"  {C_BOLD}{i}.{C_RESET} {p['name']}")
            num = prompt("Number to delete")
            if num and num.isdigit():
                idx = int(num) - 1
                if 0 <= idx < len(projects):
                    p = projects[idx]
                    if confirm(f"Delete project '{p['name']}' and ALL its data?"):
                        try:
                            supabase_db.delete_project(p["id"])
                            success(f"Deleted '{p['name']}'")
                        except Exception as e:
                            error(f"Failed to delete: {e}")
        elif choice.isdigit() and projects:
            idx = int(choice) - 1
            if 0 <= idx < len(projects):
                project_menu(projects[idx])


def _project_summary(p):
    parts = []
    for key, label in [("yt_client_id", "YT"), ("yt_client_secret", "YTS"),
                        ("yt_refresh_token", "RT")]:
        if p.get(key):
            parts.append(f"{C_GREEN}{label}{C_RESET}")
    if p.get("account_id"):
        parts.append(f"{C_GREEN}acct:{p['account_id']}{C_RESET}")
    return "  ".join(parts) if parts else ""


def project_menu(project):
    while True:
        p = supabase_db.get_project(project["id"])
        if not p:
            error("Project not found")
            return

        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}PROJECT: {p['name']}{C_RESET}")
        divider()
        print(f"  {C_BOLD}[1]{C_RESET} Configure — fields & credentials")
        print(f"  {C_BOLD}[2]{C_RESET} YouTube account — who uploads (selection)")
        print(f"  {C_BOLD}[3]{C_RESET} Doctor — check & auto-fix this project")
        print(f"  {C_BOLD}[4]{C_RESET} Status — live health check")
        print(f"  {C_BOLD}[5]{C_RESET} Instant upload — upload a video now")
        print(f"  {C_BOLD}[0]{C_RESET} Back to main menu")
        summary = _project_summary(p)
        if summary:
            print(f"\n  {summary}")
        print()

        choice = prompt("Choice").strip().upper()
        if choice == "0":
            return
        elif choice == "1":
            p = supabase_db.get_project(project["id"])
            screen_setup(p)
        elif choice == "2":
            _project_account_picker(p)
        elif choice == "3":
            p = supabase_db.get_project(project["id"]) or p
            screen_doctor(p)
        elif choice == "4":
            p = supabase_db.get_project(project["id"]) or p
            screen_status(p)
        elif choice == "5":
            _do_instant_upload(p)


# ─── Project account picker ─────────────────────────────────────────────────

def _project_account_picker(project):
    pid = project["id"]
    while True:
        clear()
        banner()
        p = supabase_db.get_project(pid) or project
        print(f"\n  {C_BOLDWHITE}UPLOAD ACCOUNT — {p['name']}{C_RESET}")
        divider()
        current = p.get("account_id", "")
        if current:
            acct = _accounts_dict().get(current)
            if acct:
                print(f"  Currently: {C_BOLD}{current}{C_RESET} — {acct.get('channel_name', '')}  "
                      f"({_account_status_str(acct)})")
            else:
                warn(f"Currently linked to '{current}' which no longer exists")
        else:
            print(f"  {C_DIM}No account linked — uploads use inline project credentials.{C_RESET}")

        accounts = _accounts_dict()
        if accounts:
            print()
            for i, (name, acct) in enumerate(accounts.items(), 1):
                ch = acct.get("channel_name", "") or acct.get("channel_id", "")
                ch_str = f" — {ch}" if ch else ""
                mark = f" {C_GREEN}← selected{C_RESET}" if name == current else ""
                print(f"  {C_BOLD}{i:2d}.{C_RESET} {name}{ch_str}{mark}")
        print()
        print(f"  {C_BOLD}[O]{C_RESET} Create a new account via OAuth")
        print(f"  {C_BOLD}[N]{C_RESET} None — unlink (keep inline credentials)")
        print(f"  {C_BOLD}[0]{C_RESET} Back")
        print()

        choice = prompt("Choice").strip().upper()
        if choice == "0":
            return
        elif choice == "O":
            _add_account_oauth()
            continue
        elif choice == "N":
            supabase_db.update_project(pid, account_id="")
            if not supabase_db.is_enabled():
                _sync_local_project(supabase_db.get_project(pid))
            success("Account unlinked")
            pause()
            return
        elif choice.isdigit() and accounts:
            idx = int(choice) - 1
            if 0 <= idx < len(accounts):
                name = list(accounts.keys())[idx]
                _link_account_to_project(pid, name)
                return


def _link_account_to_project(pid, name):
    accounts = _accounts_dict()
    acct = accounts.get(name)
    if not acct:
        error("Account not found")
        return
    # Copy the account's credentials onto the project so the whole pipeline
    # (daily_uploader, youtube_api) uses them unchanged.
    supabase_db.update_project(pid,
        account_id=name,
        yt_client_id=acct.get("client_id", ""),
        yt_client_secret=acct.get("client_secret", ""),
        yt_refresh_token=acct.get("refresh_token", ""))
    if not supabase_db.is_enabled():
        _sync_local_project(supabase_db.get_project(pid))
    success(f"Upload account set to '{name}'")
    pause()


# ─── Setup screen ─────────────────────────────────────────────────────────────

FIELD_SPEC = [
    ("yt_client_id", "YouTube Client ID", "str"),
    ("yt_client_secret", "YouTube Client Secret", "str"),
    ("yt_refresh_token", "YouTube Refresh Token", "str"),
    ("shortlink_provider", "Shortlink provider (vplink/cleanuri/tinyurl)", "str"),
    ("shortlink_api_key", "Shortlink API key", "str"),
    ("comment_moderation", "Comment mode (heldForReview/published)", "str"),
    ("mirror_title_prefix", "Title prefix (optional)", "str"),
    ("custom_title", "Custom title (optional, {title} {url})", "str"),
    ("custom_description", "Custom description (optional, {title} {url})", "str"),
    ("custom_comment", "Custom comment (optional, {url} download link)", "str"),
]


def _display_val(val, sensitive=False):
    if val is None or val == "":
        return f"{C_DIM}(empty){C_RESET}"
    val = str(val)
    if sensitive:
        return "*" * 8 + (val[-4:] if len(val) > 4 else "")
    return val if len(val) < 50 else val[:20] + "..." + val[-10:]


FIELD_VALIDATORS = {
    "shortlink_provider": lambda v: (doctor.fuzzy(v, doctor.PROVIDERS) or "",
                                     "use one of vplink / cleanuri / tinyurl"),
    "comment_moderation": lambda v: (doctor.fuzzy(v, doctor.COMMENT_MODES) or "",
                                     "use heldForReview or published"),
}


def screen_setup(project):
    pid = project["id"]

    while True:
        p = supabase_db.get_project(pid)
        if not p:
            error("Project not found")
            return

        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}CONFIGURE — {p['name']}{C_RESET}")
        divider()

        for i, (key, label, kind) in enumerate(FIELD_SPEC, 1):
            val = p.get(key, "")
            sensitive = "secret" in key or "token" in key or "key" in key or "refresh" in key
            if kind == "bool":
                display = f"{C_GREEN}✓ enabled{C_RESET}" if _is_true(val) else f"{C_DIM}✗ disabled{C_RESET}"
            else:
                display = _display_val(val, sensitive)
            print(f"  {C_BOLD}[{i:2d}]{C_RESET} {label:35s} {display}")

        print()
        print(f"  {C_BOLD}[A]{C_RESET} Pick a saved YouTube account (fills ID/secret/token)")
        print(f"  {C_BOLD}[O]{C_RESET} Run YouTube OAuth login")
        print(f"  {C_BOLD}[B]{C_RESET} Back")
        print()

        choice = prompt("Choice").strip().upper()

        if choice == "B":
            return
        elif choice == "A":
            accounts = _accounts_dict()
            name = _pick_account(accounts, "Link")
            if name:
                _link_account_to_project(pid, name)
            continue
        elif choice == "O":
            _do_oauth(p)
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(FIELD_SPEC):
                key, label, kind = FIELD_SPEC[idx]
                old = p.get(key, "")
                if kind == "bool":
                    new_val = not _is_true(old)
                    try:
                        supabase_db.update_project(pid, **{key: new_val})
                        success(f"{label}: {'enabled' if new_val else 'disabled'}")
                        p[key] = new_val
                        _sync_local_project(supabase_db.get_project(pid) or p)
                    except Exception as e:
                        error(f"Failed: {e}")
                    continue
                new_val = prompt(f"{label}", old if old != "" else None)
                if new_val is None:
                    continue
                new_val = new_val.strip()
                corrected = ""
                if key == "yt_client_id":
                    cleaned = doctor.sanitize_client_id(new_val)
                    corrected = cleaned != new_val
                    new_val = cleaned
                if key == "shortlink_provider":
                    canon = doctor.fuzzy(new_val, doctor.PROVIDERS)
                    if canon:
                        corrected = canon != new_val
                        new_val = canon
                    else:
                        error(f"{label}: use one of {', '.join(doctor.PROVIDERS)}")
                        continue
                if key == "comment_moderation":
                    canon = doctor.fuzzy(new_val, doctor.COMMENT_MODES)
                    if canon:
                        corrected = canon != new_val
                        new_val = canon
                    else:
                        error(f"{label}: use heldForReview or published")
                        continue
                if kind == "int" and new_val != "":
                    try:
                        num_val = int(float(new_val))
                    except (ValueError, TypeError):
                        error(f"{label} must be a valid number")
                        continue
                else:
                    num_val = new_val

                if num_val == old and not corrected:
                    continue
                try:
                    if kind == "int":
                        supabase_db.update_project(pid, **{key: num_val})
                    else:
                        supabase_db.update_project(pid, **{key: new_val})
                    hint = _auto(corrected)
                    success(f"{label} saved{hint}")
                    p[key] = num_val if kind == "int" else new_val
                    _sync_local_project(supabase_db.get_project(pid) or p)
                except Exception as e:
                    error(f"Failed: {e}")
                    continue

                # ── Auto-actions ──────────────────────────────────────────
                if key in ("yt_client_id", "yt_client_secret") and p.get("yt_client_id") and p.get("yt_client_secret"):
                    if confirm("Run YouTube OAuth login now to get refresh token?"):
                        p = supabase_db.get_project(pid) or p
                        _do_oauth(p)


# ─── Doctor screen ────────────────────────────────────────────────────────────

def _render_checks(checks):
    passed = fixes = issues = 0
    for c in checks:
        if c["ok"]:
            print(f"  {C_GREEN}[OK]{C_RESET}   [{c['section']}] {c['label']}" + (f" — {c['note']}" if c.get("note") else ""))
            passed += 1
        elif c.get("fix"):
            fixes += 1
            print(f"  {C_GREEN}[FIX]{C_RESET}  [{c['section']}] {c['label']} — {c['fix'][3]}")
        else:
            issues += 1
            print(f"  {C_RED}[ISSUE]{C_RESET} [{c['section']}] {c['label']}" + (f" — {c.get('note')}" if c.get("note") else ""))
    return passed, fixes, issues


def screen_doctor(project=None):
    clear()
    banner()
    if project:
        print(f"\n  {C_BOLDWHITE}DOCTOR — {project['name']}{C_RESET}")
    else:
        print(f"\n  {C_BOLDWHITE}DOCTOR — FULL SYSTEM CHECK{C_RESET}")
    print(f"  {C_DIM}Live checks + auto-correction of small mistakes...{C_RESET}\n")

    checks = []
    pid = ""
    if project:
        pid = project["id"]
        p = supabase_db.get_project(pid) or project
        checks = doctor.check_project(p)
        account_id = p.get("account_id", "")
        if account_id:
            account = supabase_db.get_account(account_id)
            if account:
                checks.extend(doctor.check_account(account))
    else:
        accounts = _accounts_dict().values()
        checks = doctor.check_accounts(list(accounts))
        try:
            projects = supabase_db.list_projects()
        except Exception:
            projects = []
        if projects:
            for p in projects:
                checks.extend(doctor.check_project(p))
        elif not supabase_db.is_enabled():
            cfg = config.load()
            synthetic = {"id": "", "name": "Local config",
                         **{k: cfg.get(k, "") for k in
                            ("yt_client_id", "yt_client_secret", "yt_refresh_token")}}
            checks.extend(doctor.check_project(synthetic))

    passed, fixes, issues = _render_checks(checks)
    print()
    if fixes:
        print(f"  {C_GREEN}{fixes} auto-fix(es) available{C_RESET}")
        if confirm("Apply all auto-fixes now?"):
            applied, failures = doctor.apply_fixes(pid, checks)
            success(f"{applied} auto-fix(es) applied")
            for f in failures:
                warn(f"  could not apply: {f}")
    if issues:
        warn(f"{issues} issue(s) remain — fix manually from the hints above")
    if passed:
        info(f"{passed} check(s) passed")
    if not fixes and issues == 0:
        success("All checks passed!")
    print()
    pause()


# ─── OAuth (project-scoped) ──────────────────────────────────────────────────

def _do_oauth(project):
    cid = project.get("yt_client_id")
    csec = project.get("yt_client_secret")
    if not cid or not csec:
        error("Set YouTube Client ID and Client Secret first (fields 1 & 2)")
        pause()
        return
    rt = _run_oauth_flow(doctor.sanitize_client_id(cid), csec)
    if rt:
        supabase_db.update_project(project["id"], yt_refresh_token=rt)
        if not supabase_db.is_enabled():
            _sync_local_project(supabase_db.get_project(project["id"]) or project)
        success("Refresh token obtained and saved to project!")
        warn("Refresh token expires in 7 days — re-run OAuth before expiry")
    pause()


# ─── Work Queue Viewer ─────────────────────────────────────────────────────

def _show_verify(project):
    pid = str(project["id"])
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}VERIFY — {project['name']} (auto-heals safe inconsistencies){C_RESET}")
    divider()
    try:
        res = verify_state.run_for(pid, owner="", fix=True)
        print()
        print(f"  {C_GREEN}{res['oks']} ok{C_RESET}  {C_YELLOW}{res['warns']} warn{C_RESET}  "
              f"{C_RED}{res['fails']} fail{C_RESET}  {C_BOLD}{res['healed']} healed{C_RESET}")
    except Exception as e:
        error(f"Verify failed: {e}")
    print()
    pause()


# ─── Instant Upload ─────────────────────────────────────────────────────────

def _do_instant_upload(project):
    pid = str(project["id"])
    if not HAS_GAPI:
        error("google-api-python-client not installed")
        return

    raw = prompt("Enter YouTube URL to upload")
    if not raw:
        error("No URL entered")
        pause()
        return

    m = re.search(r'(?:v=|youtu\.be/|youtube\.com/embed/)([\w-]{11})', raw)
    if not m:
        error("Invalid YouTube URL")
        pause()
        return
    video_id = m.group(1)

    old_pid = config.PROJECT_ID
    config.PROJECT_ID = pid
    try:
        source_url = f"https://www.youtube.com/watch?v={video_id}"
        youtube = youtube_api.get_client()
        details = youtube_api.get_video_details(youtube, video_id)
        if not details:
            error(f"Could not fetch details for {video_id}")
            pause()
            return
        if details.get("duration", 0) < 60:
            warn(f"This is a short ({details['duration']}s) — only long-form videos recommended")
            if not confirm("Upload anyway?", default_no=False):
                return

        title = details.get("title", "")
        description = details.get("description", "")
        tags = details.get("tags", [])

        info(f"Downloading: {title}")
        dl_result = download_helpers.download_video(source_url)
        if not dl_result:
            error("Download failed")
            pause()
            return
        video_path = dl_result["path"]

        info("Processing video (edit + BGM)...")
        processed = daily_uploader.process_video(video_path)
        if not processed:
            error("Processing failed or duplicate")
            pause()
            return

        info("Uploading...")
        vid = daily_uploader.upload_daily(
            processed, title=title, description=description,
            tags=tags, source_url=source_url, force=True,
            source_channel=details.get("channel_id", ""),
        )
        if vid:
            success(f"Uploaded: https://www.youtube.com/watch?v={vid}")
        else:
            error("Upload failed")
        pause()
    finally:
        config.PROJECT_ID = old_pid


# ─── QUICK DEPLOY (guided question flow) ─────────────────────────────────────

def _read_multiline(msg):
    """Read multi-line pasted content until a line equal to 'END' (or EOF).
    Returns the text with its internal line breaks preserved. A visible cue is
    printed after every line so it is never ambiguous that more input is being
    read (pasting a block with or without a trailing newline both work)."""
    print(f"  {C_CYAN}▸{C_RESET} {msg} — paste it, then type END on its own line")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip().lower() == "end":
            break
        lines.append(line)
        print(f"  {C_DIM}▸ keep pasting lines, or type END on its own line to finish{C_RESET}")
    return "\n".join(lines).strip()


def _ask_copy_or_custom(label, source, single_line=False):
    """Ask one question: use the exact value from the source video, or paste a
    custom one. Multi-line paste (END-terminated) is supported for long
    fields; single-line fields (e.g. the title) just take one line + Enter."""
    print()
    print(f"  {C_BOLDWHITE}{label}{C_RESET}")
    preview = str(source) if source else "(source has none)"
    if len(preview) > 140:
        preview = preview[:140] + "…"
    print(f"  {C_DIM}Source: {C_RESET}{preview}")
    choice = prompt(f"Copy the exact source {label.lower()}? (y=copy / n=custom)", "y").strip().lower()
    if choice in ("", "y", "yes"):
        return source
    if single_line:
        return prompt(f"Paste your custom {label.lower()}")
    return _read_multiline(f"Paste your custom {label.lower()}")


def _ask_comment():
    """Comment question: download-link default or a custom pasted comment.
    Returns None for the default (upload falls back to the download link)."""
    print()
    print(f"  {C_BOLDWHITE}Comment{C_RESET}")
    print(f"  {C_DIM}Default: download link in the comment.{C_RESET}")
    choice = prompt("Use the download-link default comment? (y=default / n=custom)", "y").strip().lower()
    if choice in ("", "y", "yes"):
        return None
    return _read_multiline("Paste your custom comment")


def _ask_processing_options():
    """Frame rate + start/end cut + copyright-free BGM, prefilled with the
    saved Settings. The answers persist as the new defaults."""
    print(f"\n  {C_BOLDWHITE}PROCESSING OPTIONS{C_RESET}")
    print(f"  {C_DIM}Frame rate, seconds cut from the start/end, and the{C_RESET}")
    print(f"  {C_DIM}copyright-free BGM source for this upload.{C_RESET}")
    s = config.load_tui_settings()

    def _num(key, default):
        try:
            return int(float(s.get(key) or default))
        except (TypeError, ValueError):
            return default

    cur_fps = _num("fps", 20)
    cur_ts = _num("trim_start", 20)
    cur_te = _num("trim_end", 10)

    raw = prompt(f"Output frame rate (default {cur_fps})").strip()
    fps = _num("fps", 20)
    if raw:
        try:
            fps = int(float(raw))
        except ValueError:
            warn(f"'{raw}' not a number — keeping {fps}")

    raw = prompt(f"Cut seconds from the START (default {cur_ts})").strip()
    ts = _num("trim_start", 20)
    if raw:
        try:
            ts = max(0, int(float(raw)))
        except ValueError:
            warn(f"'{raw}' not a number — keeping {ts}")

    raw = prompt(f"Cut seconds from the END (default {cur_te})").strip()
    te = _num("trim_end", 10)
    if raw:
        try:
            te = max(0, int(float(raw)))
        except ValueError:
            warn(f"'{raw}' not a number — keeping {te}")

    print()
    print(f"  {C_BOLDWHITE}Copyright-free BGM{C_RESET}")
    print(f"  {C_DIM}The safest is none (vocals-only). Or paste the link to a{C_RESET}")
    print(f"  {C_DIM}copyright-free music video — its audio is downloaded and{C_RESET}")
    print(f"  {C_DIM}mixed under the vocals. builtin = royalty-free library.{C_RESET}")
    cur_src = str(s.get("bgm_source") or "yt_link").strip().lower()
    bgm_choice = prompt("BGM: y=your YT music link / b=builtin / n=none", cur_src).strip().lower()
    source = "none"
    yt_url = ""
    if bgm_choice in ("y", "yes", "yt_link"):
        url = prompt("Paste the copyright-free music YouTube link",
                     (s.get("bgm_yt_url") or "").strip() or None).strip()
        if re.search(r'(?:v=|youtu\.be/|youtube\.com/embed/)([\w-]{11})', url):
            yt_url = url
            source = "yt_link"
            info("BGM: audio from your link will be mixed under the vocals")
        else:
            warn("That doesn't look like a YouTube link — BGM disabled (vocals-only)")
    elif bgm_choice in ("b", "builtin"):
        source = "builtin"
        info("BGM: builtin royalty-free library")
    else:
        info("BGM: none — vocals-only audio (most copyright-safe)")

    config.save_tui_settings(
        fps=fps, trim_start=ts, trim_end=te, bgm_source=source,
    )
    if yt_url:
        config.save_tui_setting("bgm_yt_url", yt_url)


def _upload_with_failover(processed, title, description, tags, source_url,
                          comment, source_channel):
    """Test the proxy, upload, and on any proxy-related failure re-rotate the
    pool and retry. Returns the video ID or None."""
    import proxy_pool
    s = config.get_proxy_settings()
    pool_on = _is_true(s.get("proxy_pool_enabled"))

    # Pre-flight: make sure a working proxy is active before uploading
    proxy_url = config.get_proxy_url()
    if proxy_url:
        ok, lat, note = doctor.test_proxy(proxy_url)
        if ok:
            info(f"proxy OK — {config.mask_proxy_url(proxy_url)} ({lat}s)")
        elif pool_on:
            error(f"proxy down ({note}) — re-rotating pool...")
            proxy_pool.refresh_and_activate()
        else:
            error(f"proxy down ({note}) — uploading anyway")

    retries = 4
    for attempt in range(1, retries + 1):
        info(f"uploading (attempt {attempt}/{retries})...")
        try:
            vid = daily_uploader.upload_daily(
                processed, title=title, description=description,
                tags=tags, source_url=source_url, force=True,
                source_channel=source_channel, comment=comment, raw=True,
            )
        except Exception as e:
            error(f"upload failed: {str(e)[:200]}")
            if pool_on and attempt < retries:
                info("upload blocked by proxy — re-rotating and retrying...")
                proxy_pool.refresh_and_activate()
                continue
            return None
        if vid:
            return vid
        error("upload returned no video ID")
        if pool_on and attempt < retries:
            info("re-rotating proxy and retrying...")
            proxy_pool.refresh_and_activate()
            continue
        return None
    return None


def quick_deploy_screen():
    if not HAS_GAPI:
        error("google-api-python-client not installed")
        pause()
        return

    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}QUICK DEPLOY — guided upload{C_RESET}")
    divider()

    # 1) Pick a pre-login YouTube account
    accounts = _accounts_dict()
    if not accounts:
        warn("No YouTube accounts saved — add one in main menu [2] first")
        pause()
        return
    name = _pick_account(accounts, "Select")
    if not name:
        pause()
        return
    acct = dict(accounts[name])

    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}QUICK DEPLOY — {name}{C_RESET}")
    divider()
    info("Checking account status (live token test)...")
    if not _verify_one_account(name, acct, live=True):
        error(f"Account '{name}' not verified — re-run OAuth in main menu [2]")
        pause()
        return
    success(f"Account '{name}' verified — ready to upload")

    # Point this flow at the selected account's credentials (restored after)
    env_keys = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
    old_env = {k: os.environ.get(k) for k in env_keys}
    os.environ["YT_CLIENT_ID"] = acct.get("client_id", "")
    os.environ["YT_CLIENT_SECRET"] = acct.get("client_secret", "")
    os.environ["YT_REFRESH_TOKEN"] = acct.get("refresh_token", "")
    try:
        _quick_deploy_flow(name, acct)
    finally:
        for k in env_keys:
            if old_env[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_env[k]


def _quick_deploy_flow(name, acct):
    # 2) Video link
    raw = prompt("1) Video link (paste the YouTube URL)")
    if not raw:
        error("No URL entered")
        pause()
        return
    m = re.search(r'(?:v=|youtu\.be/|youtube\.com/embed/)([\w-]{11})', raw)
    if not m:
        error("Invalid YouTube URL")
        pause()
        return
    video_id = m.group(1)
    source_url = f"https://www.youtube.com/watch?v={video_id}"

    info("Fetching video details...")
    try:
        youtube = youtube_api.get_client()
        details = youtube_api.get_video_details(youtube, video_id)
    except Exception as e:
        error(f"Could not fetch video info: {str(e)[:120]}")
        pause()
        return
    if not details:
        error("Video not found")
        pause()
        return
    if details.get("duration", 0) < 60:
        warn(f"This is a short ({details['duration']}s) — only long-form videos recommended")
        if not confirm("Upload anyway?", default_no=False):
            return

    # 3-5) Title → description → comment, one question at a time
    print(f"\n  {C_DIM}── Source: {details.get('title', '')}{C_RESET}")
    title = _ask_copy_or_custom("Title", details.get("title", ""), single_line=True)
    description = _ask_copy_or_custom("Description", details.get("description", ""))
    comment = _ask_comment()

    # 6) Proxy mode
    pm = prompt("\nEnable proxy mode? (type -y to continue, Enter = direct)").strip().lower()
    if pm in ("-y", "y", "yes", "on"):
        import proxy_pool
        config.save_proxy_settings(proxy_pool_enabled=True)
        info("Activating proxy pool...")
        if config.get_proxy_url():
            proxy_pool.ensure_working(force=True)
            success("Proxy active — uploads/downloads routed through it")
        else:
            best, msg = proxy_pool.refresh_and_activate()
            if best:
                success(msg)
            else:
                warn(msg)
    else:
        info("Proxy mode skipped — direct connection")

    # 6.5) Processing options: frame rate, start/end cut, copyright-free BGM
    _ask_processing_options()

    # 7) Process: download → vocal separation → edits → BGM mix
    info("Downloading video...")
    dl_result = download_helpers.download_video(source_url)
    if not dl_result:
        error("Download failed")
        pause()
        return
    video_path = dl_result["path"]
    download_dir = os.path.dirname(video_path)
    try:
        info("Processing (vocal separation → FFmpeg edits → BGM mix)...")
        processed = daily_uploader.process_video(video_path)
        if not processed:
            error("Processing failed or already uploaded")
            pause()
            return

        # 8) Test proxy, upload, re-rotate on proxy failure
        info("Processing done — testing proxy and uploading...")
        vid = _upload_with_failover(
            processed,
            title=title, description=description,
            tags=details.get("tags", []), source_url=source_url,
            comment=comment, source_channel=details.get("channel_id", ""),
        )
        if vid:
            success(f"Uploaded: https://www.youtube.com/watch?v={vid}")
            acct["uploads_count"] = int(acct.get("uploads_count", 0) or 0) + 1
            _save_account(name, acct)
        else:
            error("Upload failed after retries — check proxy/account, then retry")
    finally:
        shutil.rmtree(download_dir, ignore_errors=True)
        info(f"cleaned up: {download_dir}")
    pause()


# ─── Status (project-scoped) ─────────────────────────────────────────────────

def screen_status(project):
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}STATUS — {project['name']}{C_RESET}")
    print(f"  {C_DIM}Testing all credentials and connections...{C_RESET}\n")

    p = supabase_db.get_project(project["id"]) or project
    ok_count = warn_count = fail_count = 0

    def _ok(label, msg=""):
        nonlocal ok_count; ok_count += 1
        print(f"  {C_GREEN}[OK]{C_RESET}   {label}" + (f" — {msg}" if msg else ""))

    def _warn(label, msg="", fix=""):
        nonlocal warn_count; warn_count += 1
        print(f"  {C_YELLOW}[WARN]{C_RESET} {label}" + (f" — {msg}" if msg else ""))
        if fix: print(f"           {C_DIM}Fix: {fix}{C_RESET}")

    def _fail(label, msg="", fix=""):
        nonlocal fail_count; fail_count += 1
        print(f"  {C_RED}[FAIL]{C_RESET} {label}" + (f" — {msg}" if msg else ""))
        if fix: print(f"           {C_DIM}Fix: {fix}{C_RESET}")

    print(f"  {C_DIM}── Project Credentials ──{C_RESET}")
    for key, label in [
        ("yt_client_id", "YouTube Client ID"),
        ("yt_client_secret", "YouTube Client Secret"),
        ("yt_refresh_token", "YouTube Refresh Token"),
    ]:
        if p.get(key):
            _ok(f"{label} set")
        else:
            _fail(f"{label} not set", fix="Fill in Configure screen")

    account_id = p.get("account_id", "")
    if account_id:
        acct = _accounts_dict().get(account_id)
        if acct:
            _ok(f"Upload account: {account_id}", f"{acct.get('channel_name', '')} — {_account_status_str(acct)}")
        else:
            _fail("Upload account missing", fix="Pick a valid account in project menu [2]")
    else:
        _warn("No upload account linked", fix="Project menu [2] to pick a saved account")

    print(f"\n  {C_DIM}── Database ──{C_RESET}")
    try:
        supabase_db.get_upload_state(project_id=project["id"])
        if supabase_db.is_enabled():
            _ok("Connected to Supabase (cloud mode)")
        else:
            _ok("Local JSON store — data in ~/.yt-mirror/")
    except Exception as e:
        _fail("Database read failed", str(e)[:80])

    print(f"\n  {C_DIM}── Network / Proxy ──{C_RESET}")
    proxy_url = config.get_proxy_url()
    if proxy_url:
        ok, lat, note = doctor.test_proxy(proxy_url)
        if ok:
            _ok(f"Proxy {config.mask_proxy_url(proxy_url)}", f"{note} ({lat}s)")
        else:
            _fail("Proxy not reachable", fix="Check Settings → Proxy, or re-test there")
    else:
        _warn("No proxy — direct connection", fix="Settings → Proxy if YouTube blocks your IP")

    print(f"\n  {C_DIM}── YouTube ──{C_RESET}")
    cid = p.get("yt_client_id")
    csec = p.get("yt_client_secret")
    rt = p.get("yt_refresh_token")
    if cid and csec and rt:
        try:
            data = urllib.parse.urlencode({
                "client_id": cid, "client_secret": csec,
                "refresh_token": rt, "grant_type": "refresh_token",
            }).encode()
            req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=10) as resp:
                tokens = json.loads(resp.read())
                if tokens.get("access_token"):
                    _ok("YouTube token valid — can upload")
                    exp = tokens.get("expires_in", 0)
                    if exp < 3600:
                        _warn(f"Access token expires in {exp//60} min")
                else:
                    _fail("YouTube token exchange failed", fix="Re-run [O] OAuth login")
        except urllib.error.HTTPError as e:
            if e.code == 400:
                _fail("YouTube refresh token expired", fix="Re-run [O] OAuth login (7-day lifespan)")
            else:
                _fail(f"YouTube API error: {e.code}", fix="Check client_id/secret")
        except Exception as e:
            _fail(f"YouTube unreachable: {e}")
    else:
        _fail("YouTube OAuth incomplete", fix="Set client_id, secret, and run [O] OAuth login")

    divider()
    total = ok_count + warn_count + fail_count
    print(f"  {C_GREEN}{ok_count} passed{C_RESET}  {C_YELLOW}{warn_count} warnings{C_RESET}  {C_RED}{fail_count} failures{C_RESET} / {total}")
    if fail_count:
        print(f"\n  {C_RED}Fix failures above, then re-run [4] Status to verify.{C_RESET}")
    elif warn_count:
        print(f"\n  {C_YELLOW}Warnings are non-critical but should be reviewed.{C_RESET}")
    else:
        print(f"\n  {C_GREEN}All good! Ready to upload.{C_RESET}")

    print(f"\n  {C_DIM}Press Enter to return...{C_RESET}")
    input()


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _ensure_dir()
    bootstrap = _read_json(BOOTSTRAP_PATH)

    if bootstrap.get("supabase_url") and bootstrap.get("supabase_key"):
        supabase_db.configure(bootstrap["supabase_url"], bootstrap["supabase_key"])
    else:
        supabase_db.disable()
        clear()
        banner()
        print(f"\n  {C_BOLD}Running in LOCAL mode{C_RESET}")
        print(f"  {C_DIM}All project data is stored as JSON in {DATA_DIR}.{C_RESET}")
        print(f"  {C_DIM}Use main menu [4] to connect Supabase for cloud storage.{C_RESET}\n")

    try:
        main_menu()
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n  {C_DIM}Bye!{C_RESET}\n")
        sys.exit(0)
