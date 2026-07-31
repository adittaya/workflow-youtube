#!/usr/bin/env python3
"""YouTube Mirror Bot — Multi-project management TUI (all data in Supabase)."""

import json, os, sys, time, http.server, urllib.request, urllib.error, urllib.parse, re
from pathlib import Path
from datetime import datetime, timezone

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

import config
import supabase_db
import youtube_api
import daily_uploader
import download_helpers
import shortener
import verify_state

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    HAS_GAPI = True
except ImportError:
    HAS_GAPI = False

try:
    import github_api
    HAS_GH = True
except ImportError:
    HAS_GH = False

DATA_DIR = Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror")))
BOOTSTRAP_PATH = DATA_DIR / "config.json"
LOG_MAX_LINES = 80

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
    path.write_text(json.dumps(data, indent=2))

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

# ─── YouTube Helpers ──────────────────────────────────────────────────────────

def _fetch_youtube_channel_info(refresh_token, client_id, client_secret):
    if not HAS_GAPI:
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

def _parse_channel(raw):
    raw = raw.strip().rstrip("/")
    if "/@" in raw:
        handle = raw.split("/@")[-1].split("?")[0].split("/")[0]
        return f"@{handle}"
    if "/channel/" in raw:
        cid = raw.split("/channel/")[-1].split("?")[0].split("/")[0]
        if cid.startswith("UC"):
            return cid
    if "/c/" in raw:
        handle = raw.split("/c/")[-1].split("?")[0].split("/")[0]
        return f"@{handle}"
    if raw.startswith("UC") and len(raw) > 15:
        return raw
    if raw.startswith("@"):
        return raw
    return raw

# ─── Screen: Project List ─────────────────────────────────────────────────────

def project_list_screen():
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}PROJECTS{C_RESET}")
        divider()

        projects = supabase_db.list_projects()

        if not projects:
            print(f"\n  {C_DIM}No projects yet. Create one to get started.{C_RESET}")
        else:
            for i, p in enumerate(projects, 1):
                dep = f"  {C_GREEN}deployed{C_RESET}" if p.get("deployed_at") else f"  {C_DIM}not deployed{C_RESET}"
                print(f"  {C_BOLD}{i:2d}.{C_RESET} {C_BOLD}{p['name']}{C_RESET}{dep}")
                fields_set = sum(1 for k in ["yt_client_id", "yt_client_secret", "yt_refresh_token", "github_token", "github_repo"] if p.get(k))
                print(f"       {C_DIM}{fields_set}/5 credentials set{C_RESET}")
            print()

        print(f"  {C_BOLD}[A]{C_RESET} Add project")
        if projects:
            print(f"  {C_BOLD}[D]{C_RESET} Delete project")
            print(f"  {C_BOLD}[1-{len(projects)}]{C_RESET} Select project")
        print(f"  {C_BOLD}[C]{C_RESET} Change Supabase connection (re-enter URL/key)")
        print(f"  {C_BOLD}[0]{C_RESET} Quit\n")
        connected_to = _read_json(BOOTSTRAP_PATH).get("supabase_url", "")
        if connected_to:
            print(f"  {C_DIM}Connected: {connected_to}{C_RESET}")
        print()

        choice = prompt("Choice").strip().upper()

        if choice == "0":
            print(f"\n  {C_DIM}Bye!{C_RESET}\n")
            break
        elif choice == "A":
            name = prompt("Project name")
            if name:
                try:
                    p = supabase_db.create_project(name)
                    if p and p.get("id"):
                        success(f"Project '{name}' created")
                    else:
                        error("Failed to create project — name may already exist")
                except Exception as e:
                    msg = str(e)
                    if "409" in msg or "Conflict" in msg:
                        error("Project name already exists — choose a different name")
                    else:
                        error(f"Failed to create project: {e}")
            continue
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
            continue
        elif choice == "C":
            su = prompt("Supabase URL", _read_json(BOOTSTRAP_PATH).get("supabase_url", ""))
            sk = prompt("Supabase Service Key", _read_json(BOOTSTRAP_PATH).get("supabase_key", ""))
            if su and sk:
                _write_json(BOOTSTRAP_PATH, {"supabase_url": su, "supabase_key": sk})
                supabase_db.configure(su, sk)
                if supabase_db.is_enabled():
                    success("Connected to Supabase — projects reloaded")
                else:
                    error("Connection failed — check URL and key")
            continue
        elif choice.isdigit() and projects:
            idx = int(choice) - 1
            if 0 <= idx < len(projects):
                project_menu(projects[idx])
            continue

# ─── Screen: Project Menu ────────────────────────────────────────────────────

def _project_summary(p):
    parts = []
    for key, label in [("yt_client_id", "YT"), ("yt_client_secret", "YTS"),
                        ("yt_refresh_token", "RT"), ("github_token", "GH"),
                        ("github_repo", "REPO")]:
        if p.get(key):
            parts.append(f"{C_GREEN}{label}{C_RESET}")
    nch = len([c for c in p.get("channels", "").split(",") if c.strip()])
    if nch:
        parts.append(f"{C_GREEN}{nch}ch{C_RESET}")
    if p.get("deployed_at"):
        parts.append(f"{C_DIM}deployed{C_RESET}")
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
        print(f"  {C_BOLD}[1]{C_RESET} Setup & Deploy (all credentials)")
        print(f"  {C_BOLD}[S]{C_RESET} Status — check everything is right")
        print(f"  {C_BOLD}[V]{C_RESET} Verify — full self-check against the database")
        print(f"  {C_BOLD}[2]{C_RESET} View workflow logs")
        print(f"  {C_BOLD}[3]{C_RESET} Remove deployment")
        print(f"  {C_BOLD}[I]{C_RESET} Instant upload — upload a video now (bypasses cooldown)")
        print(f"  {C_BOLD}[W]{C_RESET} Work queue — view pending/done items")
        print(f"  {C_BOLD}[B]{C_RESET} Back to projects")
        print(f"  {C_BOLD}[0]{C_RESET} Quit")
        summary = _project_summary(p)
        if summary:
            print(f"\n  {summary}")
        print()

        choice = prompt("Choice").strip().upper()
        if choice == "0":
            print(f"\n  {C_DIM}Bye!{C_RESET}\n")
            return
        elif choice == "B":
            return
        elif choice == "1":
            p = supabase_db.get_project(project["id"])
            screen_setup(p)
        elif choice == "S":
            p = supabase_db.get_project(project["id"])
            screen_status(p)
        elif choice == "V":
            _show_verify(p)
        elif choice == "2":
            screen_logs(p)
        elif choice == "3":
            screen_remove_deployment(p)
        elif choice == "I":
            _do_instant_upload(p)
        elif choice == "W":
            _show_work_queue(p)

# ─── Screen: Setup & Deploy (project-scoped) ─────────────────────────────────

FIELD_SPEC = [
    ("yt_client_id", "YouTube Client ID", False),
    ("yt_client_secret", "YouTube Client Secret", False),
    ("yt_refresh_token", "YouTube Refresh Token", False),
    ("github_token", "GitHub Token (PAT)", False),
    ("github_repo", "GitHub Repo (user/repo)", False),
    ("channels", "Channel URLs (comma-separated, @abc,@xyz)", False),
    ("shortlink_provider", "Shortlink provider (vplink/cleanuri/tinyurl)", False),
    ("shortlink_api_key", "Shortlink API key", False),
    ("proxy_supabase_url", "Proxy Supabase URL (optional)", False),
    ("proxy_supabase_key", "Proxy Supabase Service Key (optional)", False),
    ("warmup_days", "Warmup days (before first upload)", True),
    ("comment_moderation", "Comment mode (heldForReview/published)", False),
    ("mirror_title_prefix", "Title prefix (optional)", False),
    ("uploads_per_day", "Uploads per day (24/N = hours between)", True),
    ("initial_backfill", "Initial backfill (videos to queue on first detect)", True),
    ("upload_schedule", "Upload schedule (comma-separated HH:MM, empty=cooldown)", False),
]

def _display_val(val, sensitive=False):
    if val is None or val == "":
        return f"{C_DIM}(empty){C_RESET}"
    val = str(val)
    if sensitive:
        return "*" * 8 + (val[-4:] if len(val) > 4 else "")
    return val if len(val) < 50 else val[:20] + "..." + val[-10:]

def _sanitize_field(key, value):
    if not value or not isinstance(value, str):
        return value
    if key == "yt_client_id":
        m = re.search(r'([\w\-]+\.apps\.googleusercontent\.com)', value)
        if m:
            return m.group(1)
        value = re.sub(r'^https?://', '', value).split('/')[0]
        value = value.split('?')[0]
    return value


def _normalize_channels(raw):
    parts = [c.strip() for c in str(raw or "").split(",") if c.strip()]
    out = []
    changed = False
    for c in parts:
        parsed = _parse_channel(c)
        if not parsed:
            continue
        if parsed != c:
            changed = True
        out.append(parsed)
    return out, changed


def _validate_schedule(raw):
    raw = str(raw or "").strip()
    if not raw:
        return None, ""
    times = []
    invalid = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            invalid.append(part)
            continue
        try:
            h, m = part.split(":")
            h, m = int(h), int(m)
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
            times.append(f"{h:02d}:{m:02d}")
        except (ValueError, IndexError):
            invalid.append(part)
    return times, ", ".join(invalid)


def _test_yt_token(cid, csec, rt):
    if not (cid and csec and rt):
        return False, "missing credentials", False
    try:
        data = urllib.parse.urlencode({
            "client_id": cid, "client_secret": csec,
            "refresh_token": rt, "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read())
            if tokens.get("access_token"):
                return True, "refresh OK", False
            return False, "no access_token returned", False
    except urllib.error.HTTPError as e:
        if e.code == 400:
            return False, "expired/invalid — re-run [O] OAuth", True
        return False, f"HTTP {e.code}", False
    except Exception as e:
        return False, str(e)[:60], False


def _test_github_token(token):
    if not token:
        return False, "", ""
    try:
        req = urllib.request.Request("https://api.github.com/user",
            headers={"Authorization": f"token {token}", "User-Agent": "yt-mirror-cli"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            user = json.loads(resp.read())
            return True, user.get("login", ""), ""
    except urllib.error.HTTPError as e:
        return False, "", f"HTTP {e.code}"
    except Exception as e:
        return False, "", str(e)[:60]


def _validate_upload_schedule_field(v):
    if not str(v or "").strip():
        return True, ""
    times, invalid = _validate_schedule(v)
    if invalid:
        return False, f"invalid slot(s): {invalid}"
    return True, ""


FIELD_VALIDATORS = {
    "shortlink_provider": lambda v: (v in ("vplink", "cleanuri", "tinyurl"),
                                     "use one of vplink / cleanuri / tinyurl"),
    "comment_moderation": lambda v: (v in ("heldForReview", "published"),
                                     "use heldForReview or published"),
    "upload_schedule": _validate_upload_schedule_field,
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
        print(f"\n  {C_BOLDWHITE}SETUP — {p['name']}{C_RESET}")
        divider()

        for i, (key, label, is_num) in enumerate(FIELD_SPEC, 1):
            val = p.get(key, "")
            sensitive = "secret" in key or "token" in key or "key" in key or "refresh" in key
            display = _display_val(val, sensitive)
            print(f"  {C_BOLD}[{i:2d}]{C_RESET} {label:35s} {display}")

        print()
        print(f"  {C_BOLD}[D]{C_RESET} Deploy to GitHub Actions")
        print(f"  {C_BOLD}[O]{C_RESET} YouTube OAuth login (get refresh token)")
        print(f"  {C_BOLD}[C]{C_RESET} Doctor — validate & fix all fields")
        print(f"  {C_BOLD}[W]{C_RESET} Reset warmup start to today")
        print(f"  {C_BOLD}[B]{C_RESET} Back")
        print()

        choice = prompt("Choice").strip().upper()

        if choice == "B":
            return
        elif choice == "D":
            _do_deploy(p)
        elif choice == "O":
            _do_oauth(p)
        elif choice == "C":
            _do_doctor(p)
        elif choice == "W":
            try:
                now = datetime.now(timezone.utc)
                wd = int(p.get("warmup_days", 0))
                supabase_db.save_upload_state({
                    "account_created": now.isoformat(),
                    "warmup_start": now.isoformat(),
                    "warmup_complete": wd <= 0,
                    "first_upload_date": None,
                    "total_uploaded": 0,
                    "last_upload_date": None,
                    "last_upload_hour": None,
                    "processed_hashes": [],
                    "yt_client_id": p.get("yt_client_id", ""),
                }, project_id=pid)
                if wd <= 0:
                    success("Warmup reset to today — 0 days means uploads start immediately")
                else:
                    success(f"Warmup reset to today — {wd} day warmup started")
                input("\n  Press Enter to continue...")
            except Exception as e:
                error(f"Failed: {e}")
                input("\n  Press Enter to continue...")
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(FIELD_SPEC):
                key, label, is_num = FIELD_SPEC[idx]
                old = p.get(key, "")
                new_val = prompt(f"{label}", old)
                if new_val is not None:
                    new_val = new_val.strip()
                    if key == "channels":
                        normalized, _changed = _normalize_channels(new_val)
                        if normalized:
                            new_val = ",".join(normalized)
                    new_val = _sanitize_field(key, new_val)
                    if new_val != old:
                        if key in FIELD_VALIDATORS:
                            ok, msg = FIELD_VALIDATORS[key](new_val)
                            if not ok:
                                error(f"{label}: {msg}")
                                continue
                        hint = ""
                        if key == "yt_client_id" and new_val != old:
                            hint = f" (auto-cleaned: {new_val})"
                        if key == "channels" and new_val != old:
                            hint = f" (normalized: {new_val})"
                        try:
                            if is_num:
                                try:
                                    num_val = int(new_val)
                                except (ValueError, TypeError):
                                    error(f"{label} must be a valid number")
                                    continue
                                supabase_db.update_project(pid, **{key: num_val})
                            else:
                                supabase_db.update_project(pid, **{key: new_val})
                            success(f"{label} saved{hint}")
                            p[key] = new_val
                        except Exception as e:
                            error(f"Failed: {e}")
                            continue

                # ── Auto-actions ──────────────────────────────────────────
                # GitHub token saved → detect username, suggest repo
                if key == "github_token" and new_val:
                    _auto_suggest_repo(pid, new_val, p.get("name", ""))

                # Client ID or secret saved → if both set, offer OAuth
                if key in ("yt_client_id", "yt_client_secret") and p.get("yt_client_id") and p.get("yt_client_secret"):
                    if confirm("Run YouTube OAuth login now to get refresh token?"):
                        p = supabase_db.get_project(pid) or p
                        _do_oauth(p)

# ─── Auto-detect GitHub username and suggest repo ──────────────────────────

def _auto_suggest_repo(pid, token, project_name):
    try:
        req = urllib.request.Request("https://api.github.com/user",
            headers={"Authorization": f"token {token}", "User-Agent": "yt-mirror-cli"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            user = json.loads(resp.read())
            username = user.get("login", "")
            if username:
                suggested = f"{username}/{project_name.replace(' ', '-').lower()}"
                info(f"Detected GitHub user: {username}")
                if confirm(f"Set repo to {suggested}?"):
                    supabase_db.update_project(pid, github_repo=suggested)
                    success(f"Repo set to {suggested}")
    except Exception as e:
        warn(f"Could not auto-detect GitHub user: {e}")

# ─── Doctor ───────────────────────────────────────────────────────────────────

def _do_doctor(project):
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}DOCTOR — {project['name']}{C_RESET}")
    print(f"  {C_DIM}Validating all fields with live checks + auto-correction...{C_RESET}\n")

    pid = project["id"]
    p = supabase_db.get_project(pid) or project
    passed = 0
    fixed = 0
    issues = 0
    fixes = []

    def report(label, ok, note="", fix=None):
        nonlocal passed, issues
        if ok:
            print(f"  {C_GREEN}[OK]{C_RESET}   {label}" + (f" — {note}" if note else ""))
            passed += 1
        elif fix is not None:
            fixes.append((label, fix[0], fix[1], fix[2]))
            print(f"  {C_GREEN}[FIX]{C_RESET}  {label} — {fix[2]}")
        else:
            print(f"  {C_RED}[ISSUE]{C_RESET} {label}" + (f" — {note}" if note else ""))
            issues += 1

    cid = p.get("yt_client_id", "")
    csec = p.get("yt_client_secret", "")
    rt = p.get("yt_refresh_token", "")
    token = p.get("github_token", "")
    repo = p.get("github_repo", "")

    # ── 1. YouTube Client ID ──
    cleaned = _sanitize_field("yt_client_id", cid)
    if cleaned and cleaned != cid:
        report("YouTube Client ID", False, fix=("yt_client_id", cleaned, f"URL prefix stripped → {cleaned}"))
        cid = cleaned
    elif cid:
        if ".apps.googleusercontent.com" not in cid:
            report("YouTube Client ID format", False,
                   "should end with .apps.googleusercontent.com — check field [1]")
        else:
            report("YouTube Client ID", True)
    else:
        report("YouTube Client ID", False, "enter your OAuth client ID in field [1]")

    # ── 2. Client Secret ──
    report("YouTube Client Secret", bool(csec), "" if csec else "enter it in field [2]")

    # ── 3. Refresh Token (live test) ──
    ok_yt, yt_note, yt_expired = _test_yt_token(cid, csec, rt)
    if ok_yt:
        report("YouTube Refresh Token", True, "valid — refresh OK")
    elif rt:
        report("YouTube Refresh Token", False,
               yt_note + (". Re-run [O] OAuth to get a fresh token" if yt_expired else ""))
    else:
        report("YouTube Refresh Token", False,
               "run [O] OAuth login after setting client ID + secret")

    # ── 4. GitHub Token (live test) ──
    ok_gh, gh_user, gh_err = _test_github_token(token)
    if ok_gh:
        report("GitHub Token", True, f"authenticated as @{gh_user}")
    elif token:
        report("GitHub Token", False, f"invalid ({gh_err or 'failed'}) — regenerate PAT with repo scope")
    else:
        report("GitHub Token", False, "enter a GitHub PAT with repo scope in field [4]")

    # ── 5. GitHub Repo ──
    if ok_gh and gh_user:
        suggested = f"{gh_user}/{str(p.get('name', '')).replace(' ', '-').lower()}"
        if not repo:
            report("GitHub Repo", False,
                   fix=("github_repo", suggested, f"auto-suggested {suggested}"))
            repo = suggested
        elif "/" not in repo:
            report("GitHub Repo format", False,
                   fix=("github_repo", suggested, f"invalid {repo!r} → {suggested}"))
            repo = suggested
        elif not repo.startswith(gh_user + "/"):
            fixed_repo = f"{gh_user}/{repo.split('/', 1)[-1]}"
            report("GitHub Repo owner", False,
                   fix=("github_repo", fixed_repo, f"token user is {gh_user} → {fixed_repo}"))
            repo = fixed_repo
        else:
            report("GitHub Repo", True, repo)
    elif repo:
        parts = repo.split("/")
        if len(parts) == 2 and parts[0] and parts[1]:
            report("GitHub Repo format", True, repo)
        else:
            report("GitHub Repo format", False, f"expected owner/repo, got {repo!r}")
    else:
        report("GitHub Repo", False, "set it in field [5]")

    # Repo accessibility
    if ok_gh and repo and "/" in repo:
        parts = repo.split("/")
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{parts[0]}/{parts[1]}",
                headers={"Authorization": f"token {token}", "User-Agent": "yt-mirror-cli"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                report("GitHub repo accessible", True, repo)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                report("GitHub repo accessible", False,
                       f"{repo} not found — create it, then run [D]eploy")
            elif e.code == 403:
                report("GitHub repo accessible", False, "token lacks access — check PAT scope")
            else:
                report("GitHub repo accessible", False, f"HTTP {e.code}")
        except Exception as e:
            report("GitHub repo accessible", False, str(e)[:60])

    # ── 6. Channels ──
    channels_raw = p.get("channels", "")
    normalized, changed = _normalize_channels(channels_raw)
    if channels_raw and normalized:
        if changed:
            report("Channels", False,
                   fix=("channels", ",".join(normalized),
                        f"{len(normalized)} normalized: {','.join(normalized)}"))
        else:
            report("Channels", True, f"{len(normalized)} configured")
    elif channels_raw and not normalized:
        report("Channels", False, "none parsed — use @handle or /channel/UCxxx, comma-separated")
    else:
        report("Channels", False, "add channel URLs in field [6]")

    # ── 7. Shortlink provider / key ──
    provider = p.get("shortlink_provider", "")
    if provider and provider not in ("vplink", "cleanuri", "tinyurl"):
        report("Shortlink provider", False,
               fix=("shortlink_provider", "vplink", f"invalid {provider!r} → vplink"))
    else:
        report("Shortlink provider", True, provider or "default: vplink")
    if provider == "vplink" and not p.get("shortlink_api_key"):
        report("Shortlink API key", False,
               "vplink requires an API key — set it in field [8]")
    else:
        report("Shortlink API key", True, "set" if p.get("shortlink_api_key") else "not needed")

    # ── 8. Comment mode ──
    cm = p.get("comment_moderation", "")
    if cm and cm not in ("heldForReview", "published"):
        report("Comment mode", False,
               fix=("comment_moderation", "published", f"invalid {cm!r} → published"))
    else:
        report("Comment mode", True, cm or "default: published")

    # ── 9. Warmup days ──
    wd = p.get("warmup_days")
    try:
        wdv = int(wd)
        if wdv < 0:
            report("Warmup days", False,
                   fix=("warmup_days", 0, f"negative {wdv} → 0"))
        else:
            report("Warmup days", True, f"{wdv} day{'s' if wdv != 1 else ''}")
    except (ValueError, TypeError):
        report("Warmup days", False, fix=("warmup_days", 0, f"invalid {wd!r} → 0"))

    # ── 10. Uploads per day ──
    upd = p.get("uploads_per_day")
    try:
        updv = int(upd)
        if updv < 1:
            report("Uploads per day", False,
                   fix=("uploads_per_day", 2, f"{updv} < 1 → 2"))
        else:
            report("Uploads per day", True, str(updv))
    except (ValueError, TypeError):
        report("Uploads per day", False, fix=("uploads_per_day", 2, f"invalid {upd!r} → 2"))

    # ── 11. Initial backfill ──
    bf = p.get("initial_backfill")
    try:
        bfv = int(bf)
        if bfv < 0:
            report("Initial backfill", False,
                   fix=("initial_backfill", 0, f"negative {bfv} → 0"))
        else:
            report("Initial backfill", True, str(bfv))
    except (ValueError, TypeError):
        report("Initial backfill", False,
               fix=("initial_backfill", 5, f"invalid {bf!r} → 5"))

    # ── 12. Upload schedule ──
    sched_raw = str(p.get("upload_schedule", "") or "").strip()
    sched_times, sched_invalid = _validate_schedule(sched_raw)
    if sched_invalid:
        good = ",".join(sched_times) if sched_times else ""
        report("Upload schedule", False,
               fix=("upload_schedule", good,
                    f"dropped invalid slot(s): {sched_invalid}" + (f" → {good}" if good else "")))
    elif sched_times:
        report("Upload schedule", True, ", ".join(sched_times))
    else:
        report("Upload schedule", True, "cooldown mode (uploads_per_day)")

    # ── 13. Proxy Supabase ──
    pu = p.get("proxy_supabase_url", "")
    pk = p.get("proxy_supabase_key", "")
    if pu and pk:
        try:
            api = pu.rstrip("/") + "/rest/v1/proxy_results?select=ip&vplink_ok=eq.true&limit=1"
            req = urllib.request.Request(api, headers={
                "apikey": pk, "Authorization": f"Bearer {pk}"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                if data:
                    report("Proxy Supabase", True, "connected, proxies available")
                else:
                    report("Proxy Supabase", False, "connected but no VPLINK-verified proxies")
        except Exception as e:
            report("Proxy Supabase", False, f"connection failed: {str(e)[:60]}")
    else:
        report("Proxy Supabase", True, "not configured (optional)")

    # ── 14. Deploy status ──
    if p.get("deployed_at"):
        report("Deployment", True, f"last deploy {p['deployed_at'][:16].replace('T', ' ')}")
    else:
        report("Deployment", False, "run [D]eploy after fields pass")

    # ── Summary + apply fixes ──
    print()
    if fixes:
        print(f"  {C_GREEN}{len(fixes)} auto-fix(es) available{C_RESET}:")
        for i, (label, _k, _v, desc) in enumerate(fixes, 1):
            print(f"     {i}. {label} — {desc}")
        print()
        if confirm("Apply all auto-fixes now?"):
            applied = 0
            for _label, key, val, _desc in fixes:
                try:
                    supabase_db.update_project(pid, **{key: val})
                    applied += 1
                    print(f"  {C_GREEN}✓{C_RESET} {key} = {val if key != 'yt_client_id' else '(cleaned)'}")
                except Exception as e:
                    error(f"Failed to set {key}: {e}")
            fixed = applied
            p = supabase_db.get_project(pid) or p
    if fixed > 0:
        success(f"{fixed} auto-fix(es) applied")
    if issues > 0:
        warn(f"{issues} issue(s) remain — fix manually from the hints above")
    if passed > 0:
        info(f"{passed} check(s) passed")
    if not fixes and issues == 0:
        success("All checks passed — ready to deploy!")
    input(f"\n  Press Enter to continue...")

# ─── Deploy ──────────────────────────────────────────────────────────────────

def _do_deploy(project):
    missing = []
    for key, label in [
        ("yt_client_id", "YouTube Client ID"),
        ("yt_client_secret", "YouTube Client Secret"),
        ("yt_refresh_token", "YouTube Refresh Token"),
        ("github_token", "GitHub Token"),
        ("github_repo", "GitHub Repo"),
    ]:
        if not project.get(key):
            missing.append(label)

    if missing:
        error(f"Missing required fields: {', '.join(missing)}")
        info("Fill all fields in Setup first, then [D]eploy")
        return

    if not HAS_GH:
        error("github_api module not found")
        return

    if not HAS_CRYPTO:
        error("cryptography library not installed. Run: pip install cryptography")
        return

    try:
        import nacl.public
    except ImportError:
        warn("pynacl not installed — secret encryption may fail. Run: pip install pynacl")

    token = project["github_token"]
    repo = project["github_repo"]
    parts = repo.split("/")
    if len(parts) != 2:
        error(f"Invalid repo format: {repo} (expected owner/name)")
        return
    owner, rn = parts[0], parts[1]

    bootstrap = _read_json(BOOTSTRAP_PATH)
    su_url = os.environ.get("SUPABASE_URL", "") or bootstrap.get("supabase_url", "")
    su_key = os.environ.get("SUPABASE_SERVICE_KEY", "") or bootstrap.get("supabase_key", "")

    channels_json = {}
    for ch in project.get("channels", "").split(","):
        ch = ch.strip()
        if ch:
            cid = _parse_channel(ch)
            channels_json[cid] = {
                "channel_id": cid,
                "channel_name": cid.lstrip("@"),
                "url": f"https://www.youtube.com/{cid}",
                "enabled": True,
                "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

    secrets = {
        "PROJECT_ID": str(project["id"]),
        "SUPABASE_URL": su_url,
        "SUPABASE_SERVICE_KEY": su_key,
        "PROXY_SUPABASE_URL": project.get("proxy_supabase_url", ""),
        "PROXY_SUPABASE_SERVICE_KEY": project.get("proxy_supabase_key", ""),
        "YT_CLIENT_ID": project.get("yt_client_id", ""),
        "YT_CLIENT_SECRET": project.get("yt_client_secret", ""),
        "YT_REFRESH_TOKEN": project.get("yt_refresh_token", ""),
        "GH_PAT": project.get("github_token", ""),
        "VPLINK_API_KEY": project.get("shortlink_api_key", ""),
        "CHANNELS": json.dumps(channels_json),
        "SETTINGS": json.dumps({
            "privacy_status": "public",
            "category_id": "22",
            "check_interval_minutes": 15,
            "max_per_cycle": 3,
            "shortener_provider": project.get("shortlink_provider", "vplink"),
            "shortener_api_key": project.get("shortlink_api_key", ""),
            "comment_moderation": project.get("comment_moderation", "heldForReview"),
            "warmup_days": int(project.get("warmup_days", 0)),
            "mirror_title_prefix": project.get("mirror_title_prefix", ""),
            "uploads_per_day": int(project.get("uploads_per_day", 2)),
            "initial_backfill": int(project.get("initial_backfill", 5)),
            "upload_schedule": project.get("upload_schedule", ""),
        }),
        "SHORTLINK_KEYS": json.dumps({"default": {
            "provider": project.get("shortlink_provider", "vplink"),
            "api_key": project.get("shortlink_api_key", ""),
        }}) if project.get("shortlink_api_key") else "{}",
    }

    print()

    # ── Check if repo exists ──
    loading("Checking GitHub repo...")
    existing = github_api.get_repo(owner, rn, token)
    repo_exists = not (isinstance(existing, dict) and existing.get("error"))

    total_steps = 6
    step_num = 0

    def step(msg):
        nonlocal step_num
        step_num += 1
        print(f"  {C_BOLD}[{step_num}/{total_steps}]{C_RESET} {msg}")

    if repo_exists:
        info(f"Repo {repo} exists — re-deploying (push code + secrets + workflow dispatch)")
        # Always push the latest local code so the deployed repo never runs stale
        step("Pushing latest code...")
        src_dir = str(Path(__file__).parent)
        remote_url = f"https://{token}@github.com/{owner}/{rn}.git"
        ok, err = github_api.git_push(src_dir, remote_url)
        if not ok:
            warn(f"Git push failed: {err} — continuing with secrets + dispatch")
        else:
            success("Latest code pushed")
        # Cancel any running/queued runs so the latest code takes effect
        step("Cancelling active workflow runs...")
        cancelled = github_api.cancel_active_runs(owner, rn, token)
        if cancelled:
            success(f"Cancelled {cancelled} active run(s)")
        else:
            info("No active runs to cancel")
        # Cancelled runs can't release their run_lock (finally never runs), so
        # orphaned locks block the new run for up to 6h. Clear the lock.
        supabase_db.release_run_lock(project_id=str(project["id"]))
        info("Cleared stale run lock")
    else:
        # Step 1: Create repo
        step(f"Creating repo {rn}...")
        resp = github_api.create_repo(token, rn, "YouTube Mirror Bot")
        if isinstance(resp, dict) and resp.get("error"):
            error(f"Create repo failed: {resp.get('message', '')}")
            return
        success("Repo created")

        # Step 2: Push code
        step("Pushing code from local...")
        src_dir = str(Path(__file__).parent)
        remote_url = f"https://{token}@github.com/{owner}/{rn}.git"
        ok, err = github_api.git_push(src_dir, remote_url)
        if not ok:
            error(f"Git push failed: {err}")
            info("Check token has repo scope and try again")
            return
        success("Code pushed")

    # Step 3/1: Set secrets
    step("Setting encrypted secrets..." if repo_exists else "Setting encrypted secrets...")
    secret_errors = github_api.set_all_secrets(owner, rn, token, secrets)
    for e in secret_errors:
        warn(e)
    if not secret_errors:
        success("All secrets set")

    # Step 4/2: Find workflow
    step("Finding workflow..." if repo_exists else "Finding workflow...")
    wf = github_api.get_mirror_workflow(owner, rn, token)
    if not wf:
        if repo_exists:
            step("Pushing code from local...")
            src_dir = str(Path(__file__).parent)
            remote_url = f"https://{token}@github.com/{owner}/{rn}.git"
            ok, err = github_api.git_push(src_dir, remote_url)
            if not ok:
                error(f"Git push failed: {err}")
                return
            success("Code pushed")
            wf = github_api.get_mirror_workflow(owner, rn, token)
        if not wf:
            warn("No youtube.yml workflow found — push may still be in progress")
    if wf:
        # Step 5/3: Enable workflow
        step("Enabling workflow..." if repo_exists else "Enabling workflow...")
        github_api.enable_workflow(owner, rn, wf["id"], token)
        success("Workflow enabled")

        # Step 6/4: Trigger immediately
        step("Triggering workflow run..." if repo_exists else "Triggering workflow run...")
        dispatch = github_api.dispatch_workflow(owner, rn, wf["id"], token, ref="main")
        if isinstance(dispatch, dict) and dispatch.get("error"):
            warn(f"Trigger failed: {dispatch.get('message', '')} — cron will pick it up")
        else:
            success("Workflow triggered!")

    # Save deployment record in project
    supabase_db.update_project(project["id"], deployed_at=datetime.now(timezone.utc).isoformat())

    divider()
    if not repo_exists:
        success(f"Deployed to {repo}!")
        info("Workflow triggered — check GitHub Actions for progress")
    else:
        success(f"Re-deployed to {repo}!")
        info("Workflow triggered — check GitHub Actions for progress")

# ─── OAuth ────────────────────────────────────────────────────────────────────

def _do_oauth(project):
    cid = project.get("yt_client_id")
    csec = project.get("yt_client_secret")
    if not cid or not csec:
        error("Set YouTube Client ID and Client Secret first (fields 1 & 2)")
        return

    import hashlib, base64 as b64

    code_verifier = b64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    code_challenge = b64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()

    scopes = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/youtube"
    params = {
        "client_id": cid,
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
        return
    server.timeout = 300

    print()
    print(f"  {C_BOLD}Open this URL in your browser and authorize:{C_RESET}")
    print(f"  {auth_url}")
    print()
    info("Waiting for callback (300s timeout)...")

    server.handle_request()
    server.server_close()

    if result["code"]:
        token_data = urllib.parse.urlencode({
            "code": result["code"],
            "client_id": cid,
            "client_secret": csec,
            "redirect_uri": "http://127.0.0.1:8085",
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }).encode()

        try:
            req = urllib.request.Request("https://oauth2.googleapis.com/token", data=token_data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=30) as resp:
                tokens = json.loads(resp.read())
                rt = tokens.get("refresh_token", "")
                if rt:
                    supabase_db.update_project(project["id"], yt_refresh_token=rt)
                    success("Refresh token obtained and saved to project!")
                    warn("Refresh token expires in 7 days — re-run [O] before expiry")
                else:
                    error("No refresh token returned — make sure OAuth consent screen is Published")
        except Exception as e:
            error(f"Token exchange failed: {e}")
    else:
        error("OAuth timed out or no code received")

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
    prompt("Press Enter to return", default="")
    return


def _show_work_queue(project):
    pid = str(project["id"])
    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}WORK QUEUE — {project['name']}{C_RESET}")
        divider()
        stats = supabase_db.get_work_stats(project_id=pid)
        print(f"  Today: {stats['done']} done  /  {stats['pending']} pending  /  {stats['failed']} failed  (total {stats['total']})")
        print()
        items = supabase_db.get_work_queue(project_id=pid, limit=20)
        if not items:
            print(f"  {C_DIM}(no items){C_RESET}")
        else:
            print(f"  {C_DIM}{'ID':>4}  {'TYPE':<8}  {'STATUS':<12}  {'TITLE':<50}  {'ERROR'}{C_RESET}")
            for it in items:
                iid = it.get('id', '')
                wtype = it.get('work_type', '')[:8]
                status = it.get('status', '')
                title = (it.get('title') or it.get('video_id') or '')[:50]
                err = (it.get('error') or '')[:30]
                color = C_GREEN if status == 'done' else (C_RED if status == 'failed' else C_YELLOW if status == 'in_progress' else C_DIM)
                print(f"  {color}{iid:>4}  {wtype:<8}  {status:<12}  {title:<50}  {err}{C_RESET}")
        print()
        print(f"  {C_BOLD}[R]{C_RESET} Refresh  {C_BOLD}[B]{C_RESET} Back")
        print()
        choice = prompt("Choice").strip().upper()
        if choice == "B":
            return


# ─── Instant Upload ─────────────────────────────────────────────────────────

def _do_instant_upload(project):
    pid = str(project["id"])
    if not HAS_GAPI:
        error("google-api-python-client not installed")
        return

    raw_channels = project.get("channels", "").strip()
    if not raw_channels:
        error("No channels configured for this project")
        input("\n  Press Enter to continue...")
        return
    channels = [_parse_channel(u) for u in raw_channels.replace(",", "\n").split("\n") if u.strip()]

    raw = prompt("Enter YouTube URL to upload (or press Enter to pick from source channels)")
    video_id = None

    if raw:
        m = re.search(r'(?:v=|youtu\.be/|youtube\.com/embed/)([\w-]{11})', raw)
        if not m:
            error("Invalid YouTube URL")
            input("\n  Press Enter to continue...")
            return
        video_id = m.group(1)
    else:
        youtube = youtube_api.get_client()
        all_vids = []
        for ch in channels:
            if not ch:
                continue
            playlist_id = youtube_api.get_channel_uploads_playlist(youtube, ch)
            if not playlist_id:
                continue
            recent = youtube_api.get_recent_videos(youtube, playlist_id, max_results=5)
            for v in recent:
                all_vids.append(v)
        if not all_vids:
            error("No videos found on source channels")
            input("\n  Press Enter to continue...")
            return
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}PICK A VIDEO TO UPLOAD{C_RESET}")
        divider()
        for i, v in enumerate(all_vids, 1):
            print(f"  {C_BOLD}[{i}]{C_RESET} {v.get('title', '?')[:60]}")
            print(f"       {v['video_id']} — {v.get('channel_title', '?')}")
        print()
        pick = prompt("Pick a video (1-{})".format(len(all_vids)))
        if not pick or not pick.isdigit() or int(pick) < 1 or int(pick) > len(all_vids):
            error("Invalid choice")
            input("\n  Press Enter to continue...")
            return
        video_id = all_vids[int(pick) - 1]["video_id"]

    old_pid = config.PROJECT_ID
    config.PROJECT_ID = pid
    try:
        source_url = f"https://www.youtube.com/watch?v={video_id}"
        youtube = youtube_api.get_client()
        details = youtube_api.get_video_details(youtube, video_id)
        if not details:
            error(f"Could not fetch details for {video_id}")
            input("\n  Press Enter to continue...")
            return
        if details.get("duration", 0) < 60:
            warn(f"This is a short ({details['duration']}s) — only long-form videos recommended")
            if not confirm("Upload anyway?"):
                return

        title = details.get("title", "")
        description = details.get("description", "")
        tags = details.get("tags", [])

        info(f"Downloading: {title}")
        dl_result = download_helpers.download_video(source_url)
        if not dl_result:
            error("Download failed")
            input("\n  Press Enter to continue...")
            return
        video_path = dl_result["path"]

        info("Processing video (edit + BGM)...")
        processed = daily_uploader.process_video(video_path)
        if not processed:
            error("Processing failed or duplicate")
            input("\n  Press Enter to continue...")
            return

        info("Uploading (bypasses cooldown)...")
        vid = daily_uploader.upload_daily(
            processed, title=title, description=description,
            tags=tags, source_url=source_url, force=True,
            source_channel=details.get("channel_id", ""),
        )
        if vid:
            success(f"Uploaded: https://www.youtube.com/watch?v={vid}")
        else:
            error("Upload failed")
        input("\n  Press Enter to continue...")
    finally:
        config.PROJECT_ID = old_pid

# ─── Screen: Status (project-scoped) ─────────────────────────────────────────

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

    # 1. Project fields
    print(f"  {C_DIM}── Project Credentials ──{C_RESET}")
    for key, label in [
        ("yt_client_id", "YouTube Client ID"),
        ("yt_client_secret", "YouTube Client Secret"),
        ("yt_refresh_token", "YouTube Refresh Token"),
        ("github_token", "GitHub Token"),
        ("github_repo", "GitHub Repo"),
    ]:
        if p.get(key):
            _ok(f"{label} set")
        else:
            _fail(f"{label} not set", fix="Fill in Setup screen and [D]eploy")

    nch = len([c for c in p.get("channels", "").split(",") if c.strip()])
    if nch:
        _ok(f"Channels: {nch} configured")
    else:
        _fail("No channels configured", fix="Add channel URLs in Setup field 6")

    # 2. Supabase connection
    print(f"\n  {C_DIM}── Supabase Database ──{C_RESET}")
    try:
        test = supabase_db.get_upload_state(project_id=project["id"])
        _ok("Connected to Supabase")
        ws = test.get("warmup_start")
        wc = test.get("warmup_complete", False)
        if ws:
            start = datetime.fromisoformat(ws)
            now = datetime.now(timezone.utc)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            days = (now - start).days
            wd = int(p.get("warmup_days", 0))
            if wc or wd <= 0:
                _ok(f"Warmup complete (started {ws[:10]})")
            else:
                remain = wd - days
                if remain < 0:
                    _ok(f"Warmup: day {days}/{wd} — auto-completing soon")
                else:
                    _ok(f"Warmup: day {days}/{wd} ({remain} days left, started {ws[:10]})")
        else:
            _warn("Warmup not started", fix="Deploy and let workflow run, or press [W]")
    except Exception as e:
        _fail("Supabase connection failed", str(e)[:80])

    # 3. GitHub access
    print(f"\n  {C_DIM}── GitHub ──{C_RESET}")
    token = p.get("github_token")
    repo = p.get("github_repo")
    if token and repo:
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}",
                headers={"Authorization": f"token {token}", "User-Agent": "yt-mirror-cli"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                _ok(f"Repo: {repo} — {data.get('description', '')[:50]}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                _fail(f"Repo {repo} not found", fix="Check repo name or create it")
            elif e.code == 401:
                _fail("GitHub token invalid", fix="Regenerate token and update Setup")
            else:
                _fail(f"GitHub API error: {e.code}", fix="Check token has repo scope")
        except Exception as e:
            _fail(f"GitHub unreachable: {e}")

        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}/actions/secrets",
                headers={"Authorization": f"token {token}", "User-Agent": "yt-mirror-cli"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                secret_names = [s["name"] for s in data.get("secrets", [])]
                required = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY", "YT_CLIENT_ID",
                            "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN", "GH_PAT", "CHANNELS", "SETTINGS"]
                optional = ["PROXY_SUPABASE_URL", "PROXY_SUPABASE_SERVICE_KEY"]
                for s in required:
                    _ok(f"Secret: {s}") if s in secret_names else _fail(f"Secret: {s} missing", fix="Run [D]eploy")
                for s in optional:
                    if s in secret_names:
                        _ok(f"Secret: {s}")
        except Exception as e:
            _warn(f"Could not check secrets: {e}")
    else:
        _fail("GitHub not configured", fix="Set token and repo in Setup and [D]eploy")

    # 4. YouTube OAuth
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

    # 5. Deployment
    print(f"\n  {C_DIM}── Deployment ──{C_RESET}")
    if p.get("deployed_at"):
        _ok(f"Deployed — last deploy at {p['deployed_at'][:16].replace('T', ' ')}")
    else:
        _warn("Not deployed yet", fix="Complete Setup and press [D]eploy")

    divider()
    total = ok_count + warn_count + fail_count
    print(f"  {C_GREEN}{ok_count} passed{C_RESET}  {C_YELLOW}{warn_count} warnings{C_RESET}  {C_RED}{fail_count} failures{C_RESET} / {total}")
    if fail_count:
        print(f"\n  {C_RED}Fix failures above, then re-run [S] Status to verify.{C_RESET}")
    elif warn_count:
        print(f"\n  {C_YELLOW}Warnings are non-critical but should be reviewed.{C_RESET}")
    else:
        print(f"\n  {C_GREEN}All good! Ready to deploy or already deployed.{C_RESET}")

    print(f"\n  {C_DIM}Press Enter to return...{C_RESET}")
    input()

# ─── Screen: Logs (project-scoped) ──────────────────────────────────────────

def screen_logs(project):
    token = project.get("github_token")
    repo = project.get("github_repo")
    if not token or not repo:
        error("GitHub not configured for this project")
        input("\n  Press Enter to continue...")
        return

    parts = repo.split("/")
    if len(parts) != 2:
        error(f"Invalid repo format: {repo} (expected owner/name)")
        input("\n  Press Enter to continue...")
        return
    owner, rn = parts[0], parts[1]

    loading(f"Fetching runs for {rn}...")
    try:
        runs = github_api.get_runs(owner, rn, token, per=10)
    except Exception as e:
        error(f"Failed to fetch runs: {e}")
        input("\n  Press Enter to continue...")
        return

    if not runs:
        print(f"\n  {C_DIM}No workflow runs found.{C_RESET}")
        input("\n  Press Enter to continue...")
        return

    while True:
        clear()
        banner()
        print(f"\n  {C_BOLDWHITE}WORKFLOW LOGS — {rn}{C_RESET}")
        divider()
        print()
        for i, run in enumerate(runs, 1):
            conclusion = run.get("conclusion") or run.get("status", "unknown")
            sc = C_GREEN if conclusion == "success" else C_RED if conclusion == "failure" else C_YELLOW
            created = run.get("created_at", "")[:16].replace("T", " ")
            print(f"  {C_BOLD}{i:2d}.{C_RESET} #{run.get('run_number', run.get('number', '?')):>4}  {sc}{conclusion:10s}{C_RESET}  {created}")
        print(f"\n  {C_BOLD}[N]{C_RESET} View log for run N")
        print(f"  {C_BOLD}[R]{C_RESET} Refresh")
        print(f"  {C_BOLD}[0]{C_RESET} Back\n")

        choice = prompt("Choice").strip().upper()
        if choice == "0":
            return
        elif choice == "R":
            loading("Refreshing runs...")
            try:
                runs = github_api.get_runs(owner, rn, token, per=10)
            except Exception:
                pass
            continue
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(runs):
                run = runs[idx]
                loading(f"Fetching logs for run #{run.get('run_number', run.get('number', '?'))}...")
                logs = github_api.get_run_logs(owner, rn, run["id"], token)
                if not logs:
                    print(f"\n  {C_DIM}No logs available.{C_RESET}")
                    input("\n  Press Enter to continue...")
                    continue
                for name, content in logs.items():
                    print(f"\n  {C_CYAN}{'─' * 56}{C_RESET}")
                    print(f"  {C_BOLD}{name}{C_RESET}")
                    print(f"  {C_CYAN}{'─' * 56}{C_RESET}")
                    lines = content.split("\n")
                    for line in lines[-LOG_MAX_LINES:]:
                        print(f"  {C_DIM}{line}{C_RESET}")
                    if len(lines) > LOG_MAX_LINES:
                        print(f"  {C_DIM}... ({len(lines) - LOG_MAX_LINES} lines hidden){C_RESET}")
                input("\n  Press Enter to continue...")

# ─── Screen: Remove Deployment (project-scoped) ──────────────────────────────

def screen_remove_deployment(project):
    clear()
    banner()
    print(f"\n  {C_BOLDWHITE}REMOVE DEPLOYMENT — {project['name']}{C_RESET}")
    divider()

    repo = project.get("github_repo")
    token = project.get("github_token")

    if not repo or not token:
        error("GitHub repo or token not configured for this project")
        input("\n  Press Enter to continue...")
        return

    parts = repo.split("/")
    if len(parts) != 2:
        error(f"Invalid repo format: {repo}")
        input("\n  Press Enter to continue...")
        return
    owner, rn = parts[0], parts[1]

    print(f"\n  {C_DIM}This will permanently delete:{C_RESET}")
    print(f"  {C_DIM}• GitHub repo: {repo}{C_RESET}")
    print(f"  {C_DIM}• All workflow runs and logs{C_RESET}")
    print(f"  {C_DIM}• Deployment record in Supabase{C_RESET}\n")

    if not confirm(f"Delete entire repo {repo}?"):
        return

    loading(f"Deleting {repo}...")
    try:
        resp = github_api.delete_repo(owner, rn, token)
        if isinstance(resp, dict) and resp.get("error"):
            error(f"GitHub API error: {resp.get('message', '')}")
        else:
            success(f"Deleted repo {repo}")
            supabase_db.update_project(project["id"], deployed_at=None)
    except Exception as e:
        error(f"Failed: {e}")

    input("\n  Press Enter to continue...")

# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _ensure_dir()
    bootstrap = _read_json(BOOTSTRAP_PATH)

    if bootstrap.get("supabase_url") and bootstrap.get("supabase_key"):
        supabase_db.configure(bootstrap["supabase_url"], bootstrap["supabase_key"])
    else:
        clear()
        banner()
        print(f"\n  {C_BOLD}First-time setup — connect to Supabase{C_RESET}")
        print(f"  {C_DIM}All project data is stored in Supabase.{C_RESET}")
        print(f"  {C_DIM}Enter your Supabase project URL and service key.{C_RESET}\n")
        su = prompt("Supabase URL")
        sk = prompt("Supabase Service Key")
        if su and sk:
            _write_json(BOOTSTRAP_PATH, {"supabase_url": su, "supabase_key": sk})
            supabase_db.configure(su, sk)
            success("Supabase configured! Now create your first project.")
        else:
            error("Supabase credentials required")
            sys.exit(1)

    if not supabase_db.is_enabled():
        error("Supabase not connected — check URL and key")
        sys.exit(1)

    try:
        project_list_screen()
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n  {C_DIM}Bye!{C_RESET}\n")
        sys.exit(0)
