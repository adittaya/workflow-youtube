#!/usr/bin/env python3
"""YouTube Mirror Bot — Full management TUI (accounts, channels, deploy, logs, settings)."""

import json, os, re, shutil, subprocess, sys, time, http.server, threading, urllib.request, urllib.parse
from pathlib import Path

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    HAS_GAPI = True
    HAS_GAPI_CLIENT = True
except ImportError:
    HAS_GAPI = False
    HAS_GAPI_CLIENT = False

try:
    import github_api
    HAS_GH = True
except ImportError:
    HAS_GH = False

# ─── Config ───────────────────────────────────────────────────────────────────

DATA_DIR = Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror")))
ACCOUNTS_PATH = DATA_DIR / "accounts.json"
GITHUB_ACCOUNTS_PATH = DATA_DIR / "github_accounts.json"
CHANNELS_PATH = DATA_DIR / "channels.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
DEPLOYMENTS_PATH = DATA_DIR / "deployments.json"
STATUS_CACHE_PATH = DATA_DIR / "status_cache.json"
SHORTLINK_KEYS_PATH = DATA_DIR / "shortlink_keys.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube",
]

TEMPLATE_REPO = "adittaya/workflow-shorturl-yt"
LOG_MAX_LINES = 80

# ─── ANSI Colors ──────────────────────────────────────────────────────────────

C_RESET  = "\033[0m"
C_BOLD   = "\033[1m"
C_DIM    = "\033[2m"
C_RED    = "\033[31m"
C_GREEN  = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE   = "\033[34m"
C_CYAN   = "\033[36m"
C_WHITE  = "\033[37m"
C_GRAY   = "\033[90m"
C_BRGREEN = "\033[92m"
C_BRCYAN  = "\033[96m"
C_BRYELLOW = "\033[93m"
C_BRRED  = "\033[91m"
C_BOLDWHITE = "\033[1;37m"

# ─── Data Layer ───────────────────────────────────────────────────────────────

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
    path.write_text(json.dumps(data, indent=2))

def load_accounts():
    return _read_json(ACCOUNTS_PATH)

def save_accounts(data):
    _write_json(ACCOUNTS_PATH, data)

def load_github_accounts():
    return _read_json(GITHUB_ACCOUNTS_PATH)

def save_github_accounts(data):
    _write_json(GITHUB_ACCOUNTS_PATH, data)

def load_channels():
    return _read_json(CHANNELS_PATH)

def save_channels(data):
    _write_json(CHANNELS_PATH, data)

def load_settings():
    defaults = {
        "active_account": "",
        "active_github": "",
        "comment_text": "Download link: {url}\n\nSubscribe for more!",
        "mirror_title_prefix": "",
        "mirror_description_suffix": "Original video link in pinned comment.",
        "privacy_status": "public",
        "category_id": "22",
        "check_interval_minutes": 15,
        "max_per_cycle": 3,
        "shortener_provider": "vplink",
        "shortener_api_key": "",
        "shortener_api_url": "",
        "comment_moderation": "heldForReview",
        "warmup_days": 14,
    }
    saved = _read_json(SETTINGS_PATH)
    return {**defaults, **saved}

def save_settings(data):
    _write_json(SETTINGS_PATH, data)

def load_deployments():
    return _read_json(DEPLOYMENTS_PATH)

def save_deployments(data):
    _write_json(DEPLOYMENTS_PATH, data)

def load_shortlink_keys():
    return _read_json(SHORTLINK_KEYS_PATH)

def save_shortlink_keys(data):
    _write_json(SHORTLINK_KEYS_PATH, data)

def load_status_cache():
    return _read_json(STATUS_CACHE_PATH)

def save_status_cache(data):
    _write_json(STATUS_CACHE_PATH, data)

# ─── UI Helpers ───────────────────────────────────────────────────────────────

def clear():
    os.system("clear" if os.name != "nt" else "cls")

def banner():
    print(f"""
{C_CYAN}{C_BOLD}╔══════════════════════════════════════════════════════════╗
║         Y O U T U B E   M I R R O R   B O T              ║
╚══════════════════════════════════════════════════════════╝{C_RESET}""")

def divider():
    print(f"  {C_DIM}{'─' * 56}{C_RESET}")

def prompt(msg, default=None):
    suffix = f" [{default}]" if default else ""
    val = input(f"  {C_CYAN}▸{C_RESET} {msg}{suffix}: ").strip()
    return val if val else (default or "")

def confirm(msg):
    val = input(f"  {C_YELLOW}?{C_RESET} {msg} (y/N): ").strip().lower()
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

def get_active_youtube():
    accounts = load_accounts()
    settings = load_settings()
    active = settings.get("active_account")
    if active and active in accounts:
        return accounts[active]
    return None

def get_active_github():
    accounts = load_github_accounts()
    settings = load_settings()
    active = settings.get("active_github")
    if active and active in accounts:
        return accounts[active]
    return None

def get_active_github_token():
    acct = get_active_github()
    return acct.get("token", "") if acct else ""

# ─── YouTube Channel Info ─────────────────────────────────────────────────────

def _fetch_youtube_channel_info(refresh_token, client_id, client_secret):
    if not HAS_GAPI_CLIENT:
        return None, None
    try:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
        )
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        resp = yt.channels().list(part="id,snippet", mine=True).execute()
        items = resp.get("items", [])
        if items:
            return items[0]["id"], items[0]["snippet"]["title"]
    except Exception:
        pass
    return None, None

# ─── Screen: YouTube Accounts ─────────────────────────────────────────────────

def screen_accounts():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}YOUTUBE ACCOUNTS{C_RESET}")
        divider()

        accounts = load_accounts()
        settings = load_settings()
        active = settings.get("active_account")
        accts = list(accounts.keys())

        if not accts:
            print(f"\n  {C_DIM}No YouTube accounts configured yet.{C_RESET}")
            print(f"  {C_DIM}Add a YouTube account to get started.{C_RESET}\n")
        else:
            for name, a in accounts.items():
                is_active = name == active
                marker = f"{C_GREEN}●{C_RESET}" if is_active else f"{C_DIM}○{C_RESET}"
                ch_name = a.get("channel_name", "?")
                ch_id = a.get("channel_id", "?")[:12]
                print(f"  {marker} {C_BOLD}{name}{C_RESET}  "
                      f"{C_DIM}@{ch_name} ({ch_id}...){C_RESET}")
            print()

        print(f"  {C_BOLD}[1]{C_RESET} Add account (OAuth login)")
        print(f"  {C_BOLD}[2]{C_RESET} Remove account")
        if accts:
            print(f"  {C_BOLD}[3]{C_RESET} Switch active account")
            print(f"  {C_BOLD}[4]{C_RESET} Validate token")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice")
        if choice == "0":
            return
        elif choice == "1":
            _add_youtube_account()
        elif choice == "2" and accts:
            _remove_youtube_account(accounts, settings)
        elif choice == "3" and accts:
            _switch_youtube_account(accounts, settings)
        elif choice == "4" and accts:
            _validate_youtube_account(accounts)

def _add_youtube_account():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}ADD YOUTUBE ACCOUNT{C_RESET}")
    divider()

    if not HAS_GAPI:
        error("Google API libraries not installed")
        info("Run: pip install google-auth-oauthlib google-api-python-client")
        input(f"\n  Press Enter to continue...")
        return

    name = prompt("Account name (e.g. main)")
    if not name:
        return
    accounts = load_accounts()
    if name in accounts:
        error("Account name already exists")
        input(f"\n  Press Enter to continue...")
        return

    client_id = prompt("Google Client ID")
    if not client_id:
        return
    client_secret = prompt("Google Client Secret")
    if not client_secret:
        return

    import hashlib, base64 as b64, secrets as _sec, socket

    code_verifier = b64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    code_challenge = b64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()

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

    _oauth_result = {"code": None}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            p = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(p.query)
            code = qs.get("code", [None])[0]
            if code:
                _oauth_result["code"] = code
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h2>Done! Close this tab.</h2></body></html>")
            else:
                self.send_response(400)
                self.end_headers()
        def log_message(self, format, *args):
            pass

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 8085))
    sock.close()

    server = http.server.HTTPServer(("127.0.0.1", 8085), _Handler)
    server.timeout = 300
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()

    print(f"\n  {C_CYAN}Open this URL in your browser:{C_RESET}\n")
    print(f"  {C_BLUE}{auth_url}{C_RESET}\n")
    print(f"  {C_DIM}After approving, the page will show an error — that's normal.{C_RESET}")
    print(f"  {C_DIM}The callback will be captured automatically.{C_RESET}\n")

    start_time = time.time()
    while _oauth_result["code"] is None and time.time() - start_time < 300:
        time.sleep(0.5)

    server.shutdown()

    if not _oauth_result["code"]:
        error("No code received — timed out")
        input(f"\n  Press Enter to continue...")
        return

    loading("Exchanging code for tokens...")
    try:
        token_data = urllib.parse.urlencode({
            "code": _oauth_result["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": "http://127.0.0.1:8085",
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=token_data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=30) as resp:
            tokens = json.loads(resp.read())
            refresh_token = tokens.get("refresh_token", "")
            if not refresh_token:
                error("No refresh token returned")
                input(f"\n  Press Enter to continue...")
                return
    except Exception as e:
        error(f"Token exchange failed: {e}")
        input(f"\n  Press Enter to continue...")
        return

    loading("Fetching channel info...")
    ch_id, ch_name = _fetch_youtube_channel_info(refresh_token, client_id, client_secret)
    if not ch_id:
        error("Could not fetch channel info — token may be invalid")
        input(f"\n  Press Enter to continue...")
        return

    accounts[name] = {
        "name": name,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "channel_id": ch_id,
        "channel_name": ch_name,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    save_accounts(accounts)

    settings = load_settings()
    if not settings.get("active_account"):
        settings["active_account"] = name
        save_settings(settings)

    print()
    success(f"Account '{name}' added!")
    info(f"Channel: @{ch_name} ({ch_id})")
    input(f"\n  Press Enter to continue...")

def _remove_youtube_account(accounts, settings):
    names = list(accounts.keys())
    print()
    for i, n in enumerate(names, 1):
        ch = accounts[n].get("channel_name", "?")
        print(f"  {C_BOLD}{i}.{C_RESET} {n}  {C_DIM}@{ch}{C_RESET}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Cancel\n")

    choice = prompt("Account number to remove")
    if not choice or choice == "0" or not choice.isdigit():
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(names):
        return
    name = names[idx]
    if confirm(f"Remove '{name}'?"):
        del accounts[name]
        save_accounts(accounts)
        if settings.get("active_account") == name:
            settings["active_account"] = list(accounts.keys())[0] if accounts else ""
            save_settings(settings)
        success(f"Removed '{name}'")
        input(f"\n  Press Enter to continue...")

def _switch_youtube_account(accounts, settings):
    names = list(accounts.keys())
    print()
    for i, n in enumerate(names, 1):
        marker = f"{C_GREEN}●{C_RESET}" if n == settings.get("active_account") else f"{C_DIM}○{C_RESET}"
        ch = accounts[n].get("channel_name", "?")
        print(f"  {marker} {C_BOLD}{i}.{C_RESET} {n}  {C_DIM}@{ch}{C_RESET}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Cancel\n")

    choice = prompt("Account number to activate")
    if not choice or choice == "0" or not choice.isdigit():
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(names):
        return
    name = names[idx]
    settings["active_account"] = name
    save_settings(settings)
    success(f"Activated '{name}'")
    input(f"\n  Press Enter to continue...")

def _validate_youtube_account(accounts):
    names = list(accounts.keys())
    print()
    for i, n in enumerate(names, 1):
        print(f"  {C_BOLD}{i}.{C_RESET} {n}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Cancel\n")

    choice = prompt("Account number to validate")
    if not choice or choice == "0" or not choice.isdigit():
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(names):
        return
    name = names[idx]
    acct = accounts[name]

    loading(f"Validating '{name}'...")
    ch_id, ch_name = _fetch_youtube_channel_info(acct["refresh_token"], acct["client_id"], acct["client_secret"])
    if ch_name:
        accounts[name]["channel_name"] = ch_name
        accounts[name]["channel_id"] = ch_id
        save_accounts(accounts)
        success(f"@{ch_name} ({ch_id}) — token valid")
    else:
        error("Token invalid or expired — re-add the account")
    input(f"\n  Press Enter to continue...")

# ─── Screen: GitHub Accounts ──────────────────────────────────────────────────

def screen_github_accounts():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}GITHUB ACCOUNTS{C_RESET}")
        divider()

        accounts = load_github_accounts()
        settings = load_settings()
        active = settings.get("active_github")
        accts = list(accounts.keys())

        if not accts:
            print(f"\n  {C_DIM}No GitHub accounts configured yet.{C_RESET}")
            print(f"  {C_DIM}Add a GitHub PAT to manage deployments.{C_RESET}\n")
        else:
            for name, a in accounts.items():
                is_active = name == active
                marker = f"{C_GREEN}●{C_RESET}" if is_active else f"{C_DIM}○{C_RESET}"
                user = a.get("username", "?")
                tok = a.get("token", "")
                masked = f"{tok[:4]}...{tok[-4:]}" if len(tok) > 8 else "****"
                print(f"  {marker} {C_BOLD}{name}{C_RESET}  "
                      f"{C_DIM}@{user}  {masked}{C_RESET}")
            print()

        print(f"  {C_BOLD}[1]{C_RESET} Add GitHub account (PAT)")
        print(f"  {C_BOLD}[2]{C_RESET} Remove account")
        if accts:
            print(f"  {C_BOLD}[3]{C_RESET} Switch active account")
            print(f"  {C_BOLD}[4]{C_RESET} Validate token")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice")
        if choice == "0":
            return
        elif choice == "1":
            _add_github_account()
        elif choice == "2" and accts:
            _remove_github_account(accounts, settings)
        elif choice == "3" and accts:
            _switch_github_account(accounts, settings)
        elif choice == "4" and accts:
            _validate_github_account(accounts)

def _add_github_account():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}ADD GITHUB ACCOUNT{C_RESET}")
    divider()

    print(f"  {C_DIM}You need a GitHub Personal Access Token.{C_RESET}")
    print(f"  {C_DIM}1. Go to github.com → Settings → Developer settings{C_RESET}")
    print(f"  {C_DIM}2. Personal access tokens → Fine-grained or Classic{C_RESET}")
    print(f"  {C_DIM}3. Scope: repo, workflow{C_RESET}\n")

    name = prompt("Account name (e.g. main)")
    if not name:
        return
    accounts = load_github_accounts()
    if name in accounts:
        error("Account name already exists")
        input(f"\n  Press Enter to continue...")
        return

    token = prompt("GitHub Personal Access Token")
    if not token:
        return

    loading("Validating token...")
    user_data = github_api.gh_user(token)
    if isinstance(user_data, dict) and user_data.get("login"):
        username = user_data["login"]
        scopes = user_data.get("_scopes", "")
        accounts[name] = {
            "name": name,
            "token": token,
            "username": username,
            "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        save_github_accounts(accounts)

        settings = load_settings()
        if not settings.get("active_github"):
            settings["active_github"] = name
            save_settings(settings)

        print()
        success(f"Added @{username}")
        scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
        if not any("repo" in s for s in scope_list):
            warn("Token missing 'repo' scope")
        if not any("workflow" in s for s in scope_list):
            warn("Token missing 'workflow' scope")
    else:
        error(f"Invalid token: {user_data.get('message', '')}")
    input(f"\n  Press Enter to continue...")

def _remove_github_account(accounts, settings):
    names = list(accounts.keys())
    print()
    for i, n in enumerate(names, 1):
        user = accounts[n].get("username", "?")
        print(f"  {C_BOLD}{i}.{C_RESET} {n}  {C_DIM}@{user}{C_RESET}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Cancel\n")

    choice = prompt("Account number to remove")
    if not choice or choice == "0" or not choice.isdigit():
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(names):
        return
    name = names[idx]
    if confirm(f"Remove '{name}'?"):
        del accounts[name]
        save_github_accounts(accounts)
        if settings.get("active_github") == name:
            settings["active_github"] = list(accounts.keys())[0] if accounts else ""
            save_settings(settings)
        success(f"Removed '{name}'")
        input(f"\n  Press Enter to continue...")

def _switch_github_account(accounts, settings):
    names = list(accounts.keys())
    print()
    for i, n in enumerate(names, 1):
        marker = f"{C_GREEN}●{C_RESET}" if n == settings.get("active_github") else f"{C_DIM}○{C_RESET}"
        user = accounts[n].get("username", "?")
        print(f"  {marker} {C_BOLD}{i}.{C_RESET} {n}  {C_DIM}@{user}{C_RESET}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Cancel\n")

    choice = prompt("Account number to activate")
    if not choice or choice == "0" or not choice.isdigit():
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(names):
        return
    name = names[idx]
    settings["active_github"] = name
    save_settings(settings)
    success(f"Activated '{name}'")
    input(f"\n  Press Enter to continue...")

def _validate_github_account(accounts):
    names = list(accounts.keys())
    print()
    for i, n in enumerate(names, 1):
        print(f"  {C_BOLD}{i}.{C_RESET} {n}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Cancel\n")

    choice = prompt("Account number to validate")
    if not choice or choice == "0" or not choice.isdigit():
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(names):
        return
    name = names[idx]
    acct = accounts[name]

    loading(f"Validating '{name}'...")
    user_data = github_api.gh_user(acct["token"])
    if isinstance(user_data, dict) and user_data.get("login"):
        accounts[name]["username"] = user_data["login"]
        save_github_accounts(accounts)
        scopes = user_data.get("_scopes", "")
        success(f"@{user_data['login']} — scopes: {scopes or 'none'}")
    else:
        error(f"Token invalid or expired: {user_data.get('message', '')}")
    input(f"\n  Press Enter to continue...")

# ─── Screen: Channels ─────────────────────────────────────────────────────────

def screen_channels():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}MONITORED CHANNELS{C_RESET}")
        divider()

        channels = load_channels()
        ch_list = list(channels.keys())

        if not ch_list:
            print(f"\n  {C_DIM}No channels to monitor.{C_RESET}")
            print(f"  {C_DIM}Add a YouTube channel URL to start mirroring.{C_RESET}\n")
        else:
            for i, cid in enumerate(ch_list, 1):
                c = channels[cid]
                alias = c.get("alias", cid)
                url = c.get("url", "")
                enabled = c.get("enabled", True)
                marker = f"{C_GREEN}●{C_RESET}" if enabled else f"{C_RED}○{C_RESET}"
                print(f"  {marker} {C_BOLD}{i}.{C_RESET} {alias}  {C_DIM}{url[:50]}{C_RESET}")
            print()

        print(f"  {C_BOLD}[1]{C_RESET} Add channel")
        print(f"  {C_BOLD}[2]{C_RESET} Remove channel")
        print(f"  {C_BOLD}[3]{C_RESET} Toggle enabled/disabled")
        print(f"  {C_BOLD}[4]{C_RESET} Bulk add (one URL per line, Ctrl+D when done)")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice")
        if choice == "0":
            return
        elif choice == "1":
            _add_channel_flow(channels)
        elif choice == "2" and ch_list:
            _remove_channel_flow(channels)
        elif choice == "3" and ch_list:
            _toggle_channel_flow(channels)
        elif choice == "4":
            _bulk_add_channels_flow(channels)

def _add_channel_flow(channels):
    print()
    url = prompt("YouTube channel URL or @handle")
    if not url:
        return

    channel_id = _extract_channel_id(url)
    if not channel_id:
        error("Invalid channel URL — use @handle or full URL")
        input(f"\n  Press Enter to continue...")
        return

    if channel_id in channels:
        error("Channel already monitored")
        input(f"\n  Press Enter to continue...")
        return

    alias = prompt("Alias (optional, for display)", channel_id.lstrip("@"))

    channels[channel_id] = {
        "url": url if url.startswith("http") else f"https://www.youtube.com/{channel_id}",
        "alias": alias,
        "enabled": True,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    save_channels(channels)
    success(f"Added: {alias} ({channel_id})")
    input(f"\n  Press Enter to continue...")

def _remove_channel_flow(channels):
    ch_list = list(channels.keys())
    print()
    for i, cid in enumerate(ch_list, 1):
        alias = channels[cid].get("alias", cid)
        print(f"  {C_BOLD}{i}.{C_RESET} {alias}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Cancel\n")

    choice = prompt("Channel number to remove")
    if not choice or choice == "0" or not choice.isdigit():
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(ch_list):
        return
    cid = ch_list[idx]
    alias = channels[cid].get("alias", cid)
    if confirm(f"Remove '{alias}'?"):
        del channels[cid]
        save_channels(channels)
        success(f"Removed '{alias}'")
        input(f"\n  Press Enter to continue...")

def _toggle_channel_flow(channels):
    ch_list = list(channels.keys())
    print()
    for i, cid in enumerate(ch_list, 1):
        c = channels[cid]
        enabled = c.get("enabled", True)
        marker = f"{C_GREEN}ON{C_RESET}" if enabled else f"{C_RED}OFF{C_RESET}"
        alias = c.get("alias", cid)
        print(f"  {C_BOLD}{i}.{C_RESET} {alias}  [{marker}]")
    print(f"\n  {C_BOLD}[0]{C_RESET} Cancel\n")

    choice = prompt("Channel number to toggle")
    if not choice or choice == "0" or not choice.isdigit():
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(ch_list):
        return
    cid = ch_list[idx]
    current = channels[cid].get("enabled", True)
    channels[cid]["enabled"] = not current
    save_channels(channels)
    state = "enabled" if not current else "disabled"
    success(f"{channels[cid].get('alias', cid)} {state}")
    input(f"\n  Press Enter to continue...")

def _bulk_add_channels_flow(channels):
    print(f"\n  {C_DIM}Paste channel URLs (one per line). Press Ctrl+D when done.{C_RESET}\n")
    added = 0
    try:
        while True:
            line = input("  ").strip()
            if not line:
                continue
            cid = _extract_channel_id(line)
            if cid and cid not in channels:
                channels[cid] = {
                    "url": line if line.startswith("http") else f"https://www.youtube.com/{cid}",
                    "alias": cid.lstrip("@"),
                    "enabled": True,
                    "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                added += 1
                success(f"Added: {cid}")
    except EOFError:
        pass
    if added:
        save_channels(channels)
        print(f"\n  {C_GREEN}Added {added} channel(s){C_RESET}")
    input(f"\n  Press Enter to continue...")

def _extract_channel_id(url):
    url = url.strip()
    if "/channel/" in url:
        return url.split("/channel/")[-1].split("/")[0].split("?")[0]
    if "@" in url:
        handle = url.split("@")[-1].split("/")[0].split("?")[0]
        return f"@{handle}"
    if url.startswith("UC") and len(url) > 20:
        return url
    if "/c/" in url:
        return url.split("/c/")[-1].split("/")[0].split("?")[0]
    if url and not url.startswith("http"):
        return f"@{url.lstrip('@')}"
    return None

# ─── Screen: Deploy ───────────────────────────────────────────────────────────

def screen_deploy():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}DEPLOY TO GITHUB ACTIONS{C_RESET}")
    divider()

    if not HAS_GH:
        error("github_api module not found")
        input(f"\n  Press Enter to continue...")
        return

    token = get_active_github_token()
    if not token:
        error("No active GitHub account — add one in GitHub Accounts first")
        input(f"\n  Press Enter to continue...")
        return

    yt_acct = get_active_youtube()
    if not yt_acct:
        error("No active YouTube account — add one in YouTube Accounts first")
        input(f"\n  Press Enter to continue...")
        return

    settings = load_settings()
    username = get_active_github().get("username", "?")

    print(f"  {C_DIM}GitHub:{C_RESET}   @{username}")
    print(f"  {C_DIM}YouTube:{C_RESET}  @{yt_acct.get('channel_name', '?')}")
    print()

    repo_name = prompt("Repo name", f"workflow-shorturl-yt")
    if not repo_name:
        return

    full_name = repo_name if repo_name.startswith("workflow-") else f"workflow-{repo_name}"

    print(f"\n  {C_DIM}This will:{C_RESET}")
    print(f"  {C_DIM}1. Create repo @{username}/{full_name}{C_RESET}")
    print(f"  {C_DIM}2. Push code from local to GitHub{C_RESET}")
    print(f"  {C_DIM}3. Set encrypted secrets (YT_CLIENT_ID, etc.){C_RESET}")
    print(f"  {C_DIM}4. Enable the youtube.yml workflow{C_RESET}")
    print()

    if not confirm(f"Deploy @{username}/{full_name}?"):
        return

    print()
    TOTAL = 7

    def step(n, msg):
        print(f"  {C_BOLD}[{n}/{TOTAL}]{C_RESET} {msg}")

    # Step 1: Check if repo exists
    step(1, f"Checking if {full_name} exists...")
    check = github_api.get_repo(username, full_name, token)
    repo_exists = not (isinstance(check, dict) and check.get("error"))

    if repo_exists:
        warn(f"Repo @{username}/{full_name} already exists")
        if not confirm("Use existing repo and just update secrets + enable workflow?"):
            return
        remote_url = f"https://{token}@github.com/{username}/{full_name}.git"
    else:
        # Step 2: Create repo
        step(2, f"Creating repo {full_name}...")
        create_resp = github_api.create_repo(token, full_name, "YouTube Mirror Bot")
        if isinstance(create_resp, dict) and create_resp.get("error"):
            error(f"Create repo failed: {create_resp.get('message', '')}")
            input(f"\n  Press Enter to continue...")
            return
        remote_url = f"https://{token}@github.com/{username}/{full_name}.git"

        # Step 3: Push code
        step(3, "Pushing code to GitHub...")
        src_dir = str(Path(__file__).parent)
        ok, err = github_api.git_push(src_dir, remote_url)
        if not ok:
            error(f"Git push failed: {err}")
            input(f"\n  Press Enter to continue...")
            return

    # Step 4: Set secrets
    step(4, "Setting encrypted secrets...")
    secrets = {
        "YT_CLIENT_ID": yt_acct.get("client_id", ""),
        "YT_CLIENT_SECRET": yt_acct.get("client_secret", ""),
        "YT_REFRESH_TOKEN": yt_acct.get("refresh_token", ""),
    }

    # Channels + settings (required by workflow)
    channels = load_channels()
    channels_json = json.dumps(channels, indent=2)
    secrets["CHANNELS"] = channels_json

    settings_payload = {
        "privacy_status": settings.get("privacy_status", "public"),
        "category_id": settings.get("category_id", "22"),
        "check_interval_minutes": settings.get("check_interval_minutes", 15),
        "max_per_cycle": settings.get("max_per_cycle", 3),
        "comment_moderation": settings.get("comment_moderation", "heldForReview"),
        "shortener_provider": settings.get("shortener_provider", "vplink"),
    }
    secrets["SETTINGS"] = json.dumps(settings_payload, indent=2)

    sk = settings.get("shortener_api_key", "")
    su = settings.get("shortener_api_url", "")
    if sk:
        secrets["SHORTENER_API_KEY"] = sk
    if su:
        secrets["SHORTENER_API_URL"] = su
    prov = settings.get("shortener_provider", "none")
    if prov == "vplink" and sk:
        secrets["VPLINK_API_KEY"] = sk

    secret_errors = github_api.set_all_secrets(username, full_name, token, secrets)
    if secret_errors:
        for e in secret_errors:
            warn(e)

    # Step 5: Find workflow
    step(5, "Finding workflow...")
    wf = github_api.get_mirror_workflow(username, full_name, token)
    if not wf:
        warn("No youtube.yml workflow found — make sure code was pushed")
    else:
        # Step 6: Enable workflow
        step(6, "Enabling workflow...")
        github_api.enable_workflow(username, full_name, wf["id"], token)

        # Step 7: Save deployment locally
        step(7, "Saving deployment record...")
        dep = {
            "name": full_name,
            "account": settings.get("active_github", ""),
            "youtube_account": settings.get("active_account", ""),
            "repo_url": f"https://github.com/{username}/{full_name}",
            "status": "deployed",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        deps = load_deployments()
        deps[full_name] = dep
        save_deployments(deps)

    print()
    success(f"Deployed: @{username}/{full_name}")
    info(f"Repo: https://github.com/{username}/{full_name}")
    info("Workflow will run automatically within ~1 minute")
    input(f"\n  Press Enter to continue...")

# ─── Screen: Remove Deployment ────────────────────────────────────────────────

def screen_remove_deployment():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}REMOVE DEPLOYMENT{C_RESET}")
        divider()

        deps = load_deployments()
        dep_list = list(deps.values())

        if not dep_list:
            print(f"\n  {C_DIM}No deployments to remove.{C_RESET}\n")
            input(f"  Press Enter to continue...")
            return

        for i, d in enumerate(dep_list, 1):
            status = d.get("status", "?")
            sc = C_GREEN if status == "deployed" else C_YELLOW if status == "unknown" else C_RED
            acct = d.get("account", "?")
            print(f"  {C_BOLD}{i}.{C_RESET} {d['name']}  "
                  f"{sc}{status}{C_RESET}  {C_DIM}@{acct}{C_RESET}")
        print(f"\n  {C_BOLD}[N]{C_RESET} Remove deployment N")
        print(f"  {C_BOLD}[a]{C_RESET} Nuke ALL deployments")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice")
        if choice == "0":
            return
        elif choice == "a":
            if confirm(f"DELETE ALL {len(dep_list)} DEPLOYMENTS? This removes GitHub repos too!"):
                loading("Nuking all deployments...")
                deleted = 0
                errors = 0
                for d in dep_list:
                    acct_name = d.get("account", "")
                    gh_accounts = load_github_accounts()
                    acct = gh_accounts.get(acct_name, {})
                    token = acct.get("token", "")
                    owner = acct.get("username", acct_name)
                    if token:
                        resp = github_api.delete_repo(owner, d["name"], token)
                        if isinstance(resp, dict) and resp.get("error"):
                            errors += 1
                        else:
                            deleted += 1
                    repo_dir = DATA_DIR / "repos" / d["name"]
                    if repo_dir.exists():
                        shutil.rmtree(repo_dir, ignore_errors=True)
                save_deployments({})
                if errors:
                    warn(f"Nuked {deleted} deployments ({errors} failed)")
                else:
                    success(f"Nuked {deleted} deployments")
                input(f"\n  Press Enter to continue...")
                return
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(dep_list):
                d = dep_list[idx]
                if confirm(f"Remove '{d['name']}'? (deletes GitHub repo)"):
                    loading(f"Removing {d['name']}...")
                    acct_name = d.get("account", "")
                    gh_accounts = load_github_accounts()
                    acct = gh_accounts.get(acct_name, {})
                    token = acct.get("token", "")
                    owner = acct.get("username", acct_name)
                    if token:
                        resp = github_api.delete_repo(owner, d["name"], token)
                        if isinstance(resp, dict) and resp.get("error"):
                            error(f"GitHub API error: {resp.get('message', '')}")
                        else:
                            success(f"Deleted GitHub repo")
                    repo_dir = DATA_DIR / "repos" / d["name"]
                    if repo_dir.exists():
                        shutil.rmtree(repo_dir, ignore_errors=True)
                    deps = load_deployments()
                    deps.pop(d["name"], None)
                    save_deployments(deps)
                    success(f"Removed {d['name']}")
                    input(f"\n  Press Enter to continue...")

# ─── Screen: Sync from GitHub ─────────────────────────────────────────────────

def screen_sync():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}SYNC FROM GITHUB{C_RESET}")
    divider()

    gh_accounts = load_github_accounts()
    if not gh_accounts:
        error("No GitHub accounts configured")
        input(f"\n  Press Enter to continue...")
        return

    existing = load_deployments()
    new_repos = []
    updated_repos = []
    errors = []

    for name, acct in gh_accounts.items():
        tok = acct.get("token", "")
        if not tok:
            errors.append(f"@{name}: no token")
            continue
        loading(f"Scanning @{acct.get('username', name)}...")
        try:
            repos = github_api.get_mirror_repos(tok)
            if isinstance(repos, dict) and repos.get("_rate_limited"):
                errors.append(f"@{name}: rate-limited by GitHub API")
                continue
            for repo in repos:
                rn = repo["name"]
                owner = repo["owner"]["login"]
                status = "unknown"
                try:
                    runs = github_api.get_runs(owner, rn, tok, per=1)
                    last = runs[0] if runs else None
                    status = (last.get("conclusion") or last.get("status", "unknown")) if last else "no_runs"
                except Exception as e:
                    errors.append(f"{rn}: {str(e)[:40]}")

                if rn in existing:
                    existing[rn]["status"] = status
                    existing[rn]["account"] = name
                    updated_repos.append(rn)
                else:
                    existing[rn] = {
                        "name": rn,
                        "account": name,
                        "repo_url": repo["html_url"],
                        "status": status,
                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                    new_repos.append(rn)
        except Exception as e:
            errors.append(f"@{name}: {str(e)[:40]}")

    save_deployments(existing)

    print()
    if new_repos or updated_repos:
        success("Sync complete")
    else:
        info("Nothing new found")
    print(f"  {C_DIM}New:{C_RESET} {len(new_repos)}  "
          f"{C_DIM}Updated:{C_RESET} {len(updated_repos)}  "
          f"{C_DIM}Total:{C_RESET} {len(existing)}")
    if new_repos:
        print(f"  {C_GREEN}New repos:{C_RESET} {', '.join(new_repos)}")
    if errors:
        for e in errors:
            warn(e)
    input(f"\n  Press Enter to continue...")

# ─── Screen: View Logs ────────────────────────────────────────────────────────

def screen_logs():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}VIEW WORKFLOW LOGS{C_RESET}")
    divider()

    token = get_active_github_token()
    if not token:
        error("No active GitHub account")
        input(f"\n  Press Enter to continue...")
        return

    repos = github_api.get_mirror_repos(token)
    if isinstance(repos, dict) and repos.get("_rate_limited"):
        error("Rate-limited by GitHub API. Try again later.")
        input(f"\n  Press Enter to continue...")
        return
    if not repos:
        print(f"\n  {C_DIM}No workflow-* repos found.{C_RESET}")
        input(f"  Press Enter to continue...")
        return

    print()
    for i, repo in enumerate(repos, 1):
        print(f"  {C_BOLD}{i}.{C_RESET} {repo['name']}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Back\n")

    choice = prompt("Select repo")
    if not choice or choice == "0" or not choice.isdigit():
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(repos):
        return

    repo = repos[idx]
    owner = repo["owner"]["login"]
    rn = repo["name"]

    loading(f"Fetching runs for {rn}...")
    runs = github_api.get_runs(owner, rn, token, per=10)
    if not runs:
        print(f"\n  {C_DIM}No workflow runs found.{C_RESET}")
        input(f"  Press Enter to continue...")
        return

    print()
    print(f"  {C_BOLD}Recent runs for {rn}:{C_RESET}")
    print()
    for i, run in enumerate(runs, 1):
        conclusion = run.get("conclusion") or run.get("status", "unknown")
        sc = C_GREEN if conclusion == "success" else C_RED if conclusion == "failure" else C_YELLOW
        created = run.get("created_at", "")[:16].replace("T", " ")
        print(f"  {C_BOLD}{i:2d}.{C_RESET} #{run['number']:4d}  "
              f"{sc}{conclusion:10s}{C_RESET}  {created}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Back\n")

    choice2 = prompt("Select run")
    if not choice2 or choice2 == "0" or not choice2.isdigit():
        return

    idx2 = int(choice2) - 1
    if idx2 < 0 or idx2 >= len(runs):
        return

    run = runs[idx2]
    print()
    loading(f"Fetching logs for run #{run['number']}...")

    logs = github_api.get_run_logs(owner, rn, run["id"], token)
    if not logs:
        print(f"\n  {C_DIM}No logs available.{C_RESET}")
        input(f"  Press Enter to continue...")
        return

    for name, content in logs.items():
        print(f"\n  {C_CYAN}{'─' * 56}{C_RESET}")
        print(f"  {C_BOLD}{name}{C_RESET}")
        print(f"  {C_CYAN}{'─' * 56}{C_RESET}")
        lines = content.split("\n")
        for line in lines[-LOG_MAX_LINES:]:
            print(f"  {C_DIM}{line}{C_RESET}")
        if len(lines) > LOG_MAX_LINES:
            print(f"  {C_DIM}... ({len(lines) - LOG_MAX_LINES} lines hidden){C_RESET}")

    input(f"\n  Press Enter to continue...")

# ─── Screen: Trigger Workflow ─────────────────────────────────────────────────

def screen_dispatch():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}MANUALLY TRIGGER WORKFLOW{C_RESET}")
    divider()

    token = get_active_github_token()
    if not token:
        error("No active GitHub account")
        input(f"\n  Press Enter to continue...")
        return

    repos = github_api.get_mirror_repos(token)
    if isinstance(repos, dict) and repos.get("_rate_limited"):
        error("Rate-limited by GitHub API")
        input(f"\n  Press Enter to continue...")
        return
    if not repos:
        print(f"\n  {C_DIM}No workflow-* repos found.{C_RESET}")
        input(f"  Press Enter to continue...")
        return

    print()
    for i, repo in enumerate(repos, 1):
        print(f"  {C_BOLD}{i}.{C_RESET} {repo['name']}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Back\n")

    choice = prompt("Select repo to trigger")
    if not choice or choice == "0" or not choice.isdigit():
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(repos):
        return

    repo = repos[idx]
    owner = repo["owner"]["login"]
    rn = repo["name"]

    print(f"\n  {C_DIM}Run mode:{C_RESET}")
    print(f"  {C_BOLD}[1]{C_RESET} Mirror (check + upload new videos)")
    print(f"  {C_BOLD}[2]{C_RESET} Daily upload (process + upload 1 video)")
    print(f"  {C_BOLD}[3]{C_RESET} Both (mirror + daily upload)")
    print(f"  {C_BOLD}[4]{C_RESET} Dry run (no upload)\n")
    mode_choice = prompt("Mode", "1")
    mode_map = {"1": "mirror", "2": "daily_upload", "3": "both", "4": "mirror"}
    mode = mode_map.get(mode_choice, "mirror")
    dry_run = "true" if mode_choice == "4" else "false"

    inputs = {"mode": mode, "dry_run": dry_run}

    if not confirm(f"Trigger workflow on {rn} (mode: {mode})?"):
        return

    loading(f"Dispatching workflow on {rn}...")
    wf = github_api.get_mirror_workflow(owner, rn, token)
    if not wf:
        error("No workflow found")
        input(f"\n  Press Enter to continue...")
        return

    resp = github_api.dispatch_workflow(owner, rn, wf["id"], token, inputs=inputs)
    if isinstance(resp, dict) and resp.get("error"):
        error(f"Dispatch failed: {resp.get('message', '')}")
    else:
        success(f"Workflow triggered on {rn} (mode: {mode})")
    input(f"\n  Press Enter to continue...")

# ─── Screen: Status ───────────────────────────────────────────────────────────

def screen_status():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}STATUS{C_RESET}")
    divider()

    yt_accounts = load_accounts()
    gh_accounts = load_github_accounts()
    channels = load_channels()
    settings = load_settings()
    active_yt = settings.get("active_account")
    active_gh = settings.get("active_github")

    # YouTube account
    print(f"  {C_DIM}YouTube accounts:{C_RESET} {len(yt_accounts)}")
    if active_yt and active_yt in yt_accounts:
        ch = yt_accounts[active_yt].get("channel_name", "?")
        print(f"  {C_DIM}Active YouTube:{C_RESET}   {C_GREEN}{active_yt}{C_RESET} (@{ch})")
    elif yt_accounts:
        print(f"  {C_DIM}Active YouTube:{C_RESET}   {C_YELLOW}none selected{C_RESET}")
    else:
        print(f"  {C_DIM}Active YouTube:{C_RESET}   {C_RED}no accounts{C_RESET}")

    # GitHub account
    print(f"  {C_DIM}GitHub accounts:{C_RESET}  {len(gh_accounts)}")
    if active_gh and active_gh in gh_accounts:
        user = gh_accounts[active_gh].get("username", "?")
        print(f"  {C_DIM}Active GitHub:{C_RESET}    {C_GREEN}{active_gh}{C_RESET} (@{user})")
    elif gh_accounts:
        print(f"  {C_DIM}Active GitHub:{C_RESET}    {C_YELLOW}none selected{C_RESET}")
    else:
        print(f"  {C_DIM}Active GitHub:{C_RESET}    {C_RED}no accounts{C_RESET}")

    enabled_ch = sum(1 for c in channels.values() if c.get("enabled", True))
    print(f"  {C_DIM}Channels:{C_RESET}        {len(channels)} ({enabled_ch} enabled)")
    print(f"  {C_DIM}Interval:{C_RESET}        {settings.get('check_interval_minutes', 15)} min")
    print()

    # YouTube stats
    if active_yt and active_yt in yt_accounts:
        acct = yt_accounts[active_yt]
        if HAS_GAPI_CLIENT:
            try:
                creds = Credentials(
                    token=None,
                    refresh_token=acct["refresh_token"],
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=acct["client_id"],
                    client_secret=acct["client_secret"],
                )
                yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
                resp = yt.channels().list(part="statistics,snippet", mine=True).execute()
                items = resp.get("items", [])
                if items:
                    stats = items[0].get("statistics", {})
                    print(f"  {C_DIM}YouTube channel:{C_RESET}")
                    print(f"    Videos:      {stats.get('videoCount', '?')}")
                    print(f"    Subscribers: {stats.get('subscriberCount', '?')}")
                    print(f"    Views:       {stats.get('viewCount', '?')}")
                    print()
            except Exception as e:
                warn(f"Could not fetch YouTube stats: {e}")

    # Mirror stats
    state_path = DATA_DIR / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text("utf-8"))
            stats = state.get("stats", {})
            processed = state.get("processed", {})
            print(f"  {C_DIM}Mirror stats:{C_RESET}")
            print(f"    Mirrored:  {stats.get('total_mirrored', 0)}")
            print(f"    Comments:  {stats.get('total_comments', 0)}")
            print(f"    Shortened: {stats.get('total_shortened', 0)}")
            print(f"    Tracked:   {len(processed)} videos")
        except Exception:
            pass
    else:
        print(f"  {C_DIM}Mirror stats:{C_RESET} (no runs yet)")

    # Daily upload stats
    upload_state_path = DATA_DIR / "upload_state.json"
    if upload_state_path.exists():
        try:
            us = json.loads(upload_state_path.read_text("utf-8"))
            warmup_start = us.get("warmup_start")
            warmup_complete = us.get("warmup_complete", False)
            total = us.get("total_uploaded", 0)
            last = us.get("last_upload_date", "never")
            processed_count = len(us.get("processed_hashes", []))

            if warmup_start:
                from datetime import datetime
                start = datetime.fromisoformat(warmup_start)
                days = (datetime.utcnow() - start).days
                try:
                    warmup_days = int(json.loads((DATA_DIR / "settings.json").read_text("utf-8")).get("warmup_days", 14))
                except Exception:
                    warmup_days = 14
                if warmup_complete or days >= warmup_days:
                    warmup_str = f"{C_GREEN}complete{C_RESET}"
                else:
                    remaining = warmup_days - days
                    warmup_str = f"{C_YELLOW}day {days}/{warmup_days} ({remaining} days left){C_RESET}"
                warmup_date_str = warmup_start[:10]
            else:
                warmup_str = f"{C_DIM}not started{C_RESET}"
                warmup_date_str = "-"

            print()
            print(f"  {C_DIM}Daily uploads:{C_RESET}")
            print(f"    Warmup:     {warmup_str}")
            print(f"    Started:    {warmup_date_str}")
            print(f"    Uploaded:   {total} videos")
            print(f"    Last:       {last}")
            print(f"    Processed:  {processed_count} videos")
        except Exception:
            pass

    # Deployment status
    deps = load_deployments()
    if deps:
        print()
        print(f"  {C_DIM}Deployments:{C_RESET}")
        for name, d in deps.items():
            status = d.get("status", "?")
            sc = C_GREEN if status == "deployed" else C_YELLOW if status == "unknown" else C_RED
            print(f"    {name}  {sc}{status}{C_RESET}")

        # Check latest workflow runs
        token = get_active_github_token()
        if token:
            print()
            print(f"  {C_DIM}Latest workflow runs:{C_RESET}")
            for name, d in deps.items():
                repo_url = d.get("repo_url", "")
                parts = repo_url.replace("https://github.com/", "").split("/")
                if len(parts) >= 2:
                    owner, rn = parts[0], parts[1]
                    try:
                        runs = github_api.get_runs(owner, rn, token, per=1)
                        if runs:
                            run = runs[0]
                            conclusion = run.get("conclusion") or run.get("status", "?")
                            sc = C_GREEN if conclusion == "success" else C_RED if conclusion == "failure" else C_YELLOW
                            created = run.get("created_at", "")[:16].replace("T", " ")
                            print(f"    {rn}  {sc}{conclusion}{C_RESET}  {C_DIM}{created}{C_RESET}")
                    except Exception:
                        pass

    print()
    input(f"  Press Enter to continue...")

# ─── Screen: Settings ─────────────────────────────────────────────────────────

def screen_settings():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}SETTINGS{C_RESET}")
        divider()

        s = load_settings()
        prov = s.get("shortener_provider", "none")
        prov_label = {"vplink": "VPLink", "cleanuri": "CleanURI", "tinyurl": "TinyURL", "generic": "Generic"}.get(prov, "none")
        mod = s.get("comment_moderation", "heldForReview")
        mod_label = "View-only (owner only)" if mod == "heldForReview" else "Public (everyone sees)"
        print(f"  {C_DIM}Comment text:{C_RESET}    {s.get('comment_text', '')[:50]}")
        print(f"  {C_DIM}Comment mode:{C_RESET}    {mod_label}")
        print(f"  {C_DIM}Title prefix:{C_RESET}    {s.get('mirror_title_prefix', '') or '(none)'}")
        print(f"  {C_DIM}Desc suffix:{C_RESET}     {(s.get('mirror_description_suffix', '') or '(none)')[:50]}")
        print(f"  {C_DIM}Privacy:{C_RESET}        {s.get('privacy_status', 'public')}")
        print(f"  {C_DIM}Category:{C_RESET}       {s.get('category_id', '22')}")
        print(f"  {C_DIM}Interval:{C_RESET}       {s.get('check_interval_minutes', 15)} min")
        print(f"  {C_DIM}Max/cycle:{C_RESET}      {s.get('max_per_cycle', 3)}")
        print(f"  {C_DIM}Shortener:{C_RESET}      {prov_label} (manage in [L] Shortlink keys)")
        print()
        print(f"  {C_BOLD}[1]{C_RESET} Comment text (use {url} for link)")
        print(f"  {C_BOLD}[2]{C_RESET} Comment mode (view-only / public)")
        print(f"  {C_BOLD}[3]{C_RESET} Title prefix")
        print(f"  {C_BOLD}[4]{C_RESET} Description suffix")
        print(f"  {C_BOLD}[5]{C_RESET} Privacy status (public/unlisted/private)")
        print(f"  {C_BOLD}[6]{C_RESET} Category ID")
        print(f"  {C_BOLD}[7]{C_RESET} Check interval (minutes)")
        print(f"  {C_BOLD}[8]{C_RESET} Max videos per cycle")
        print(f"  {C_BOLD}[9]{C_RESET} Warmup days (before first upload)")
        print(f"  {C_BOLD}[R]{C_RESET} Reset warmup from today")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice")
        if choice == "0":
            return
        elif choice == "1":
            val = prompt("Comment text (use {url} for link)", s.get("comment_text"))
            if val:
                s["comment_text"] = val
                save_settings(s)
                success("Saved")
        elif choice == "2":
            print(f"\n  {C_DIM}Comment moderation:{C_RESET}")
            print(f"  {C_BOLD}[1]{C_RESET} View-only — only you see comments (heldForReview)")
            print(f"  {C_BOLD}[2]{C_RESET} Public — everyone sees comments (published)\n")
            mod_choice = prompt("Mode")
            if mod_choice == "1":
                s["comment_moderation"] = "heldForReview"
                save_settings(s)
                success("Comments will be view-only (owner only)")
            elif mod_choice == "2":
                s["comment_moderation"] = "published"
                save_settings(s)
                success("Comments will be public")
            else:
                error("Invalid choice")
        elif choice == "3":
            val = prompt("Title prefix", s.get("mirror_title_prefix"))
            s["mirror_title_prefix"] = val
            save_settings(s)
            success("Saved")
        elif choice == "4":
            val = prompt("Description suffix", s.get("mirror_description_suffix"))
            s["mirror_description_suffix"] = val
            save_settings(s)
            success("Saved")
        elif choice == "5":
            val = prompt("Privacy status", s.get("privacy_status"))
            if val in ("public", "unlisted", "private"):
                s["privacy_status"] = val
                save_settings(s)
                success("Saved")
            else:
                error("Must be: public, unlisted, or private")
        elif choice == "6":
            val = prompt("Category ID", s.get("category_id"))
            if val.isdigit():
                s["category_id"] = val
                save_settings(s)
                success("Saved")
        elif choice == "7":
            val = prompt("Check interval (minutes)", str(s.get("check_interval_minutes", 15)))
            if val.isdigit() and int(val) >= 5:
                s["check_interval_minutes"] = int(val)
                save_settings(s)
                success("Saved")
            else:
                error("Must be >= 5 minutes")
        elif choice == "8":
            val = prompt("Max videos per cycle", str(s.get("max_per_cycle", 3)))
            if val.isdigit() and int(val) >= 1:
                s["max_per_cycle"] = int(val)
                save_settings(s)
                success("Saved")
            else:
                error("Must be >= 1")
        elif choice == "9":
            val = prompt("Warmup days (days before first upload)", str(s.get("warmup_days", 14)))
            if val.isdigit() and int(val) >= 0:
                s["warmup_days"] = int(val)
                save_settings(s)
                success("Saved")
            else:
                error("Must be >= 0")
        elif choice.upper() == "R":
            confirm = prompt("Reset warmup from today? (y/n)", "n")
            if confirm.lower() == "y":
                from datetime import datetime
                us_path = DATA_DIR / "upload_state.json"
                try:
                    us = json.loads(us_path.read_text("utf-8"))
                except Exception:
                    us = {}
                us["warmup_start"] = datetime.utcnow().isoformat()
                us["warmup_complete"] = False
                us_path.write_text(json.dumps(us, indent=2), "utf-8")
                success("Warmup reset from today")
            else:
                info("Cancelled")

# ─── Screen: Shortlink Keys ───────────────────────────────────────────────────

def screen_shortlink_keys():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}SHORTLINK API KEYS{C_RESET}")
        divider()

        keys = load_shortlink_keys()
        settings = load_settings()
        active_provider = settings.get("shortener_provider", "none")
        active_key = settings.get("shortener_api_key", "")
        key_list = list(keys.keys())

        if not key_list:
            print(f"\n  {C_DIM}No API keys configured yet.{C_RESET}")
            print(f"  {C_DIM}Add keys for VPLink, CleanURI, TinyURL, etc.{C_RESET}\n")
        else:
            for name, k in keys.items():
                provider = k.get("provider", "?")
                api_key = k.get("api_key", "")
                is_active = (provider == active_provider and api_key == active_key)
                marker = f"{C_GREEN}●{C_RESET}" if is_active else f"{C_DIM}○{C_RESET}"
                masked = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "****"
                print(f"  {marker} {C_BOLD}{name}{C_RESET}  "
                      f"{C_DIM}{provider}{C_RESET}  {masked}")
            print()

        print(f"  {C_BOLD}[1]{C_RESET} Add API key")
        print(f"  {C_BOLD}[2]{C_RESET} Remove key")
        if key_list:
            print(f"  {C_BOLD}[3]{C_RESET} Use key (set as active)")
            print(f"  {C_BOLD}[4]{C_RESET} Test key")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice")
        if choice == "0":
            return
        elif choice == "1":
            _add_shortlink_key(keys)
        elif choice == "2" and key_list:
            _remove_shortlink_key(keys)
        elif choice == "3" and key_list:
            _use_shortlink_key(keys)
        elif choice == "4" and key_list:
            _test_shortlink_key(keys)

def _add_shortlink_key(keys):
    print(f"\n  {C_DIM}Select provider:{C_RESET}")
    print(f"  {C_BOLD}[1]{C_RESET} VPLink     — vplink.in (earn per click)")
    print(f"  {C_BOLD}[2]{C_RESET} CleanURI   — cleanuri.com")
    print(f"  {C_BOLD}[3]{C_RESET} TinyURL    — tinyurl.com")
    print(f"  {C_BOLD}[4]{C_RESET} Generic    — custom API endpoint\n")

    prov_choice = prompt("Provider")
    prov_map = {"1": "vplink", "2": "cleanuri", "3": "tinyurl", "4": "generic"}
    provider = prov_map.get(prov_choice, "")
    if not provider:
        error("Invalid choice")
        input(f"\n  Press Enter to continue...")
        return

    name = prompt("Key name (e.g. main)")
    if not name:
        return
    if name in keys:
        error("Key name already exists")
        input(f"\n  Press Enter to continue...")
        return

    api_key = prompt("API key")
    if not api_key:
        return

    keys[name] = {
        "name": name,
        "provider": provider,
        "api_key": api_key,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    save_shortlink_keys(keys)
    success(f"Added '{name}' ({provider})")
    input(f"\n  Press Enter to continue...")

def _remove_shortlink_key(keys):
    names = list(keys.keys())
    print()
    for i, n in enumerate(names, 1):
        prov = keys[n].get("provider", "?")
        print(f"  {C_BOLD}{i}.{C_RESET} {n}  {C_DIM}{prov}{C_RESET}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Cancel\n")

    choice = prompt("Key number to remove")
    if not choice or choice == "0" or not choice.isdigit():
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(names):
        return
    name = names[idx]
    if confirm(f"Remove '{name}'?"):
        del keys[name]
        save_shortlink_keys(keys)
        success(f"Removed '{name}'")
        input(f"\n  Press Enter to continue...")

def _use_shortlink_key(keys):
    names = list(keys.keys())
    print()
    for i, n in enumerate(names, 1):
        prov = keys[n].get("provider", "?")
        print(f"  {C_BOLD}{i}.{C_RESET} {n}  {C_DIM}{prov}{C_RESET}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Cancel\n")

    choice = prompt("Key number to activate")
    if not choice or choice == "0" or not choice.isdigit():
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(names):
        return
    name = names[idx]
    k = keys[name]
    settings = load_settings()
    settings["shortener_provider"] = k["provider"]
    settings["shortener_api_key"] = k["api_key"]
    save_settings(settings)
    success(f"Activated '{name}' ({k['provider']})")
    input(f"\n  Press Enter to continue...")

def _test_shortlink_key(keys):
    names = list(keys.keys())
    print()
    for i, n in enumerate(names, 1):
        prov = keys[n].get("provider", "?")
        print(f"  {C_BOLD}{i}.{C_RESET} {n}  {C_DIM}{prov}{C_RESET}")
    print(f"\n  {C_BOLD}[0]{C_RESET} Cancel\n")

    choice = prompt("Key number to test")
    if not choice or choice == "0" or not choice.isdigit():
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(names):
        return
    name = names[idx]
    k = keys[name]
    provider = k["provider"]
    api_key = k["api_key"]

    loading(f"Testing {provider} key...")
    import shortener
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    result = shortener.shorten_url(test_url, api_key=api_key, provider=provider)
    if result != test_url:
        success(f"Shortened: {result}")
    else:
        error("Shortener returned original URL — check key")
    input(f"\n  Press Enter to continue...")

# ─── Screen: Dispatch Local ───────────────────────────────────────────────────

def screen_dispatch_local():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}RUN MIRROR LOCALLY{C_RESET}")
    divider()

    accounts = load_accounts()
    channels = load_channels()
    settings = load_settings()
    active = settings.get("active_account")

    if not active or active not in accounts:
        error("No active YouTube account — add one in YouTube Accounts first")
        input(f"\n  Press Enter to continue...")
        return
    if not channels:
        error("No channels to monitor — add one in Channels first")
        input(f"\n  Press Enter to continue...")
        return

    print(f"  {C_DIM}Active account:{C_RESET} @{accounts[active].get('channel_name', '?')}")
    print(f"  {C_DIM}Channels:{C_RESET} {len(channels)}")
    print()

    if not confirm("Run mirror cycle now?"):
        return

    loading("Running mirror cycle...")
    print()

    env = os.environ.copy()
    acct = accounts[active]
    env["YT_CLIENT_ID"] = acct["client_id"]
    env["YT_CLIENT_SECRET"] = acct["client_secret"]
    env["YT_REFRESH_TOKEN"] = acct["refresh_token"]
    env["YT_DATA_DIR"] = str(DATA_DIR)

    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "mirror.py")],
        env=env, timeout=600,
    )
    print()
    if result.returncode == 0:
        success("Mirror cycle completed")
    else:
        error(f"Mirror cycle failed (exit code {result.returncode})")
    input(f"\n  Press Enter to continue...")

# ─── Main Menu ────────────────────────────────────────────────────────────────

def main_menu():
    while True:
        clear()
        banner()

        yt_accounts = load_accounts()
        gh_accounts = load_github_accounts()
        channels = load_channels()
        settings = load_settings()
        active_yt = settings.get("active_account")
        active_gh = settings.get("active_github")
        deps = load_deployments()

        # Status line
        if active_yt and active_yt in yt_accounts:
            ch = yt_accounts[active_yt].get("channel_name", "?")
            print(f"  {C_DIM}YT:{C_RESET} {C_GREEN}@{ch}{C_RESET}  "
                  f"{C_DIM}GH:{C_RESET} {len(gh_accounts)}  "
                  f"{C_DIM}Ch:{C_RESET} {len(channels)}  "
                  f"{C_DIM}Deploys:{C_RESET} {len(deps)}")
        elif yt_accounts:
            print(f"  {C_DIM}YT:{C_RESET} {C_YELLOW}none{C_RESET}  "
                  f"{C_DIM}GH:{C_RESET} {len(gh_accounts)}  "
                  f"{C_DIM}Ch:{C_RESET} {len(channels)}  "
                  f"{C_DIM}Deploys:{C_RESET} {len(deps)}")
        else:
            print(f"  {C_YELLOW}No accounts configured — add one to get started{C_RESET}")

        print()
        print(f"  {C_BOLD}[1]{C_RESET} YouTube accounts")
        print(f"  {C_BOLD}[2]{C_RESET} GitHub accounts")
        print(f"  {C_BOLD}[3]{C_RESET} Monitored channels")
        print(f"  {C_BOLD}[4]{C_RESET} Deploy to GitHub Actions")
        print(f"  {C_BOLD}[5]{C_RESET} Remove deployment")
        print(f"  {C_BOLD}[6]{C_RESET} Sync from GitHub")
        print(f"  {C_BOLD}[7]{C_RESET} View workflow logs")
        print(f"  {C_BOLD}[8]{C_RESET} Trigger workflow (remote)")
        print(f"  {C_BOLD}[9]{C_RESET} Run mirror now (local)")
        print(f"  {C_BOLD}[L]{C_RESET} Shortlink API keys")
        print(f"  {C_BOLD}[S]{C_RESET} Status overview")
        print(f"  {C_BOLD}[T]{C_RESET} Settings")
        print(f"  {C_BOLD}[D]{C_RESET} Doctor (diagnostics)")
        print(f"  {C_BOLD}[0]{C_RESET} Quit\n")

        choice = prompt("Choice")
        if choice == "0" or choice.lower() == "q":
            print(f"\n  {C_DIM}Bye!{C_RESET}\n")
            break
        elif choice == "1":
            screen_accounts()
        elif choice == "2":
            screen_github_accounts()
        elif choice == "3":
            screen_channels()
        elif choice == "4":
            screen_deploy()
        elif choice == "5":
            screen_remove_deployment()
        elif choice == "6":
            screen_sync()
        elif choice == "7":
            screen_logs()
        elif choice == "8":
            screen_dispatch()
        elif choice == "9":
            screen_dispatch_local()
        elif choice.lower() == "l":
            screen_shortlink_keys()
        elif choice.lower() == "s":
            screen_status()
        elif choice.lower() == "t":
            screen_settings()
        elif choice.lower() == "d":
            screen_doctor()

def screen_doctor():
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}DIAGNOSTIC DOCTOR{C_RESET}")
    print(f"  {C_DIM}Checking everything...{C_RESET}\n")

    checks = []

    def ok(label, msg=""):
        checks.append(("ok", label, msg))
        print(f"  {C_GREEN}[OK]{C_RESET}   {label}" + (f" — {msg}" if msg else ""))

    def warn(label, msg="", fix=""):
        checks.append(("warn", label, msg, fix))
        print(f"  {C_YELLOW}[WARN]{C_RESET} {label}" + (f" — {msg}" if msg else ""))
        if fix:
            print(f"           {C_DIM}Fix: {fix}{C_RESET}")

    def fail(label, msg="", fix=""):
        checks.append(("fail", label, msg, fix))
        print(f"  {C_RED}[FAIL]{C_RESET} {label}" + (f" — {msg}" if msg else ""))
        if fix:
            print(f"           {C_DIM}Fix: {fix}{C_RESET}")

    # 1. Python
    import sys
    v = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 8):
        ok(f"Python {v}")
    else:
        fail(f"Python {v}", "Need 3.8+", "Install Python 3.8+: pkg install python")

    # 2. yt-dlp
    import shutil, subprocess
    ytdlp_path = shutil.which("yt-dlp")
    if ytdlp_path:
        try:
            r = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=10)
            ver = r.stdout.strip()
            ok(f"yt-dlp {ver}", ytdlp_path)
        except Exception:
            warn("yt-dlp found but not responding", fix="Update: yt-dlp -U")
    else:
        fail("yt-dlp not found", fix="Install: pkg install yt-dlp  or  pip install yt-dlp")

    # 2b. ffmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        try:
            r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
            ver = r.stdout.split("\n")[0] if r.stdout else "installed"
            ok(f"ffmpeg", ver[:50])
        except Exception:
            warn("ffmpeg found but not responding")
    else:
        warn("ffmpeg not found", "Required for video processing", "Install: sudo apt install ffmpeg")

    # 2c. demucs
    try:
        r = subprocess.run(["python3", "-c", "import demucs; print(demucs.__version__)"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            ok(f"demucs {r.stdout.strip()}", "Vocal separation")
        else:
            warn("demucs not installed", "Optional: vocal separation for processing",
                 "Install: pip install demucs torch")
    except Exception:
        warn("demucs check failed", "Optional: vocal separation for processing")

    # 3. Config files
    for fname in ["accounts.json", "channels.json", "settings.json", "state.json",
                   "deployments.json", "shortlink_keys.json", "upload_state.json"]:
        p = DATA_DIR / fname
        if not p.exists():
            warn(f"{fname} missing", fix="Run: yt-mirror (auto-creates)")
        else:
            try:
                json.loads(p.read_text())
                ok(fname)
            except json.JSONDecodeError as e:
                fail(f"{fname} — corrupted JSON", str(e), fix=f"Fix JSON syntax or delete {fname}")

    # 4. YouTube account
    accounts = load_accounts()
    settings = load_settings()
    active_yt = settings.get("active_account")
    if not accounts:
        fail("No YouTube accounts", fix="Add via: [1] YouTube accounts → [A] Add")
    elif not active_yt:
        warn("No active YouTube account selected", fix="Set via: [1] YouTube accounts → [S] Select")
    elif active_yt not in accounts:
        warn(f"Active account '{active_yt}' not found", fix="Re-select via: [1] YouTube accounts → [S] Select")
    else:
        acct = accounts[active_yt]
        ok(f"YouTube: @{acct.get('channel_name', '?')} ({active_yt[:12]}...)")

        # 4b. Test token refresh
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            creds = Credentials(
                token=None,
                refresh_token=acct["refresh_token"],
                token_uri="https://oauth2.googleapis.com/token",
                client_id=acct["client_id"],
                client_secret=acct["client_secret"],
            )
            yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
            resp = yt.channels().list(part="statistics", id=acct["channel_id"]).execute()
            subs = resp["items"][0]["statistics"]["subscriberCount"]
            ok(f"Token valid — {subs} subscribers")
        except Exception as e:
            err = str(e)
            if "invalid_grant" in err or "Token has been expired or revoked" in err:
                fail("YouTube token expired/revoked", err[:80], fix="Re-authenticate: python3 get_refresh_token.py")
            else:
                fail("YouTube token test failed", err[:80], fix="Check client_id/client_secret in accounts.json")

    # 5. GitHub account
    gh_accounts = load_github_accounts()
    active_gh = settings.get("active_github")
    if not gh_accounts:
        warn("No GitHub accounts", "Deploy won't work", "Add via: [2] GitHub accounts → [A] Add")
    elif not active_gh:
        warn("No active GitHub account", fix="Set via: [2] GitHub accounts → [S] Select")
    elif active_gh not in gh_accounts:
        warn(f"Active GitHub '{active_gh}' not found", fix="Re-select via: [2] GitHub accounts → [S] Select")
    else:
        gh = gh_accounts[active_gh]
        ok(f"GitHub: {gh.get('username', '?')}")

        # 5b. Test token
        import urllib.request
        try:
            req = urllib.request.Request("https://api.github.com/user", headers={
                "Authorization": f"token {gh['token']}",
                "User-Agent": "yt-mirror-cli",
            })
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            repos = data.get("public_repos", 0)
            ok(f"GitHub token valid — {repos} repos")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                fail("GitHub token invalid/expired", fix="Re-add account with new token")
            else:
                warn(f"GitHub API error: {e.code}")
        except Exception as e:
            warn(f"GitHub API unreachable: {e}")

    # 6. Channels
    channels = load_channels()
    if not channels:
        warn("No channels monitored", fix="Add via: [3] Monitored channels → [A] Add")
    else:
        ok(f"{len(channels)} channel(s) monitored")
        for ch in channels[:5]:
            name = ch.get("channel_name") or ch.get("channel_id", "?")[:20]
            vid = ch.get("last_video_id", "none")
            print(f"         {C_DIM}• @{name} — last: {vid}{C_RESET}")

    # 7. Shortlink keys
    keys = load_shortlink_keys()
    prov = settings.get("shortener_provider", "none")
    if prov == "none":
        ok("Shortener disabled (direct URLs)")
    elif not keys:
        warn(f"Shortener set to '{prov}' but no API keys", fix="Add via: [L] Shortlink API keys → [A] Add")
    else:
        active_keys = [k for k in keys.values() if k.get("provider") == prov]
        if active_keys:
            ok(f"Shortener: {prov} — {len(active_keys)} key(s)")
        else:
            warn(f"No '{prov}' keys found", fix=f"Add via: [L] Shortlink API keys → [A] Add (provider: {prov})")

    # 8. Disk space
    import os
    st = os.statvfs(str(DATA_DIR))
    free_mb = (st.f_bavail * st.f_frsize) / (1024 * 1024)
    if free_mb < 100:
        warn(f"Low disk space: {free_mb:.0f}MB free", fix="Free space or use larger storage")
    else:
        ok(f"Disk space: {free_mb:.0f}MB free")

    # 9. Network
    try:
        urllib.request.urlopen("https://www.googleapis.com", timeout=5)
        ok("Network: YouTube API reachable")
    except Exception:
        warn("Network: can't reach YouTube API", fix="Check internet connection")

    # Summary
    n_ok = sum(1 for c in checks if c[0] == "ok")
    n_warn = sum(1 for c in checks if c[0] == "warn")
    n_fail = sum(1 for c in checks if c[0] == "fail")
    divider()
    if n_fail == 0 and n_warn == 0:
        print(f"  {C_GREEN}All checks passed — ready to mirror!{C_RESET}")
    else:
        print(f"  {C_GREEN}{n_ok} passed{C_RESET}  "
              f"{C_YELLOW}{n_warn} warnings{C_RESET}  "
              f"{C_RED}{n_fail} failures{C_RESET}")
        if n_fail:
            print(f"\n  {C_RED}Fix the failures above before running mirror.{C_RESET}")
    print(f"\n  {C_DIM}Press Enter to return...{C_RESET}")
    input()


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for f in ["accounts.json", "github_accounts.json", "channels.json", "settings.json", "deployments.json", "state.json", "shortlink_keys.json"]:
        p = DATA_DIR / f
        if not p.exists():
            p.write_text("{}")
    try:
        main_menu()
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n  {C_DIM}Bye!{C_RESET}\n")
        sys.exit(0)
