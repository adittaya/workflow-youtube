#!/usr/bin/env python3
"""yt-auto — YT VIDEO AUTOMATION command-line interface (local-first).

Runs the detect → process → upload pipeline as a continuous local daemon
(or a single pass), manages channels, credentials and state — all backed by
local JSON files under ~/.yt-mirror/ when Supabase is not configured.

    yt-auto run                 continuous daemon (detect → upload → sleep)
    yt-auto run --once          one detect+upload+verify pass
    yt-auto setup               guided first-time configuration
    yt-auto oauth               YouTube OAuth login (get refresh token)
    yt-auto channels list|add|remove
    yt-auto status [--json]     current state summary
    yt-auto logs [N] [--json]   recent upload log entries
    yt-auto verify [--no-fix]   self-verification of state
    yt-auto version
"""
import argparse
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

VERSION = "0.1.0"


def _import_backend():
    import config
    import supabase_db
    import daily_uploader
    import verify_state
    return config, supabase_db, daily_uploader, verify_state


def _import_loop():
    import continuous_loop
    return continuous_loop


def _save_local_settings(patch):
    import config
    config.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    try:
        existing = json.loads(config.SETTINGS_PATH.read_text("utf-8"))
    except Exception:
        pass
    existing.update(patch)
    fd, tmp = tempfile.mkstemp(dir=str(config.SETTINGS_PATH.parent),
                               prefix="settings.", suffix=".tmp")
    try:
        os.write(fd, json.dumps(existing, indent=2).encode("utf-8"))
        os.close(fd)
        os.chmod(tmp, 0o600)
        os.rename(tmp, str(config.SETTINGS_PATH))
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _pid(args):
    return os.environ.get("PROJECT_ID", getattr(args, "project", "") or "")


# ─── commands ────────────────────────────────────────────────────────────

def cmd_run(args):
    import config
    import supabase_db
    import verify_state
    import daily_uploader
    cl = _import_loop()

    if getattr(args, "duration", None):
        cl.RUN_DURATION = float(args.duration) * 3600

    pid = _pid(args)

    if args.once:
        owner = f"{pid}:local-{time.time():.0f}"
        acquired, current = supabase_db.acquire_run_lock(project_id=pid, owner=owner, ttl_hours=6)
        if not acquired:
            print(f"lock held by {current} — use `yt-auto run` to wait for it")
            return 1
        try:
            try:
                summary = verify_state.run_for(pid, owner=owner, fix=True)
                config.log(f"verify: {summary['oks']} ok, {summary['warns']} warn, "
                           f"{summary['fails']} fail, {summary['healed']} healed")
            except Exception as e:
                config.log(f"verify error: {e}")
            found = cl.detect_and_queue()
            config.log(f"detect: {'new videos queued' if found else 'nothing new'}")
            uploaded = cl.upload_one_pending()
            config.log(f"upload: {'uploaded' if uploaded else 'nothing uploaded'}")
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        finally:
            supabase_db.release_run_lock(project_id=pid, owner=owner)
        return 0

    cl.main()
    return 0


def cmd_status(args):
    import config
    import supabase_db
    import daily_uploader
    pid = _pid(args)

    state = daily_uploader.load_upload_state()
    status = daily_uploader.get_status()
    channels = config.load_channels()
    cursors = supabase_db.get_all_cursors(project_id=pid)
    pending = status and list(state.get("pending_hashes", [])) or []
    try:
        work = supabase_db.get_work_stats(project_id=pid)
    except Exception:
        work = {}
    try:
        alerts = supabase_db.get_open_alerts(project_id=pid, limit=10)
    except Exception:
        alerts = []

    if args.json:
        print(json.dumps({
            "mode": "supabase" if supabase_db.is_enabled() else "local",
            "project_id": pid,
            "channels": len(channels),
            "cursors": len(cursors),
            "pending": len(pending),
            **{k: status.get(k) for k in (
                "warmup_day", "warmup_total", "warmup_complete", "can_upload",
                "upload_reason", "total_uploaded", "last_upload", "processed_count")},
            "work": work,
            "open_alerts": len(alerts),
        }, indent=2))
        return 0

    print(f"yt-auto {VERSION} — mode: {'supabase (cloud)' if supabase_db.is_enabled() else 'local JSON files'}")
    print(f"project: {pid or '(default)'}")
    print(f"channels: {len(channels)} tracked, {len(cursors)} with cursor")
    print(f"warmup: day {status['warmup_day']}/{status['warmup_total']} "
          f"({'complete' if status['warmup_complete'] else 'in progress'})")
    print(f"upload: {'ready' if status['can_upload'] else status['upload_reason']}")
    print(f"total uploaded: {status['total_uploaded']}  (last: {status['last_upload'] or 'never'})")
    print(f"processed: {status['processed_count']}  pending queue: {len(pending)}")
    if work:
        print(f"work today: {work.get('total', 0)} total, {work.get('done', 0)} done, "
              f"{work.get('failed', 0)} failed, {work.get('pending', 0)} pending")
    if alerts:
        print(f"open alerts ({len(alerts)}):")
        for a in alerts[:5]:
            print(f"  [{a.get('severity')}] {a.get('check_name')}: {a.get('message')}")
    return 0


def cmd_logs(args):
    import supabase_db
    pid = _pid(args)
    n = args.count if args.count else 10
    logs = supabase_db.get_upload_logs(limit=n, project_id=pid)
    if args.json:
        print(json.dumps({"logs": logs}, indent=2))
        return 0
    if not logs:
        print("no uploads logged yet")
        return 0
    for l in logs:
        print(f"{l.get('upload_date', '?'):10} {l.get('upload_time', '?')[:19]}  "
              f"{l.get('video_id', ''):12} {l.get('title', '')}")
    return 0


def cmd_verify(args):
    import supabase_db
    import verify_state
    pid = _pid(args)
    res = verify_state.run_for(pid, owner=f"cli-{time.time():.0f}", fix=not args.no_fix)
    return 1 if res["fails"] else 0


def cmd_oauth(args):
    import config
    cfg = config.load()
    cid = os.environ.get("YT_CLIENT_ID", "") or cfg.get("yt_client_id", "")
    csec = os.environ.get("YT_CLIENT_SECRET", "") or cfg.get("yt_client_secret", "")
    if not cid or not csec:
        print("YouTube client ID/secret missing.")
        print("Set YT_CLIENT_ID + YT_CLIENT_SECRET env vars, or run `yt-auto setup` first.")
        return 1

    import base64
    import hashlib
    import http.server
    import urllib.parse
    import urllib.request

    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()

    scopes = ("https://www.googleapis.com/auth/youtube.upload "
              "https://www.googleapis.com/auth/youtube.force-ssl "
              "https://www.googleapis.com/auth/youtube")
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
            code = urllib.parse.parse_qs(parsed.query).get("code", [None])[0]
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

    try:
        server = http.server.HTTPServer(("0.0.0.0", 8085), Handler)
    except OSError:
        print("port 8085 in use — close the other app or wait")
        return 1
    server.timeout = 300

    print("Open this URL in your browser and authorize:")
    print("  " + auth_url)
    print("Waiting for callback (300s timeout)...")
    server.handle_request()
    server.server_close()

    if not result["code"]:
        print("OAuth timed out or no code received")
        return 1

    token_data = urllib.parse.urlencode({
        "code": result["code"],
        "client_id": cid,
        "client_secret": csec,
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
            config.save({"yt_refresh_token": rt})
            print("Refresh token saved to ~/.yt-mirror/config.json")
            print("Refresh tokens expire every 7 days — re-run `yt-auto oauth` before expiry.")
            return 0
        print("No refresh token returned — make sure the OAuth consent screen is Published")
        return 1
    except Exception as e:
        print(f"token exchange failed: {e}")
        return 1


def cmd_setup(args):
    import config
    import supabase_db
    pid = _pid(args)

    cfg = config.load()
    if not cfg.get("yt_client_id") or not cfg.get("yt_client_secret"):
        print("Step 1/4 — YouTube API credentials (https://console.cloud.google.com/apis/credentials)")
        cid = input("OAuth Client ID: ").strip()
        csec = input("OAuth Client Secret: ").strip()
        if cid and csec:
            config.save({"yt_client_id": cid, "yt_client_secret": csec})
    if not config.is_configured():
        print("  → next run `yt-auto oauth` to get a refresh token.")

    print("Step 2/4 — channels to mirror (one per line, blank to finish)")
    while True:
        url = input("  channel URL or @handle: ").strip()
        if not url:
            break
        ok, res = config.add_channel(url)
        print(f"  {'ok: ' + res if ok else 'error: ' + res}")

    if supabase_db.is_enabled():
        print("Step 3/4 — cloud mode: configure upload schedule via the VPLINKYT TUI instead.")
    else:
        print("Step 3/4 — upload settings (defaults shown, Enter keeps them)")
        try:
            uploads_per_day = int(input("  uploads per day [2]: ").strip() or "2")
        except ValueError:
            uploads_per_day = 2
        try:
            warmup_days = int(input("  warmup days (0 = none) [0]: ").strip() or "0")
        except ValueError:
            warmup_days = 0
        try:
            backfill = int(input("  initial backfill videos [5]: ").strip() or "5")
        except ValueError:
            backfill = 5
        schedule = input("  upload schedule (e.g. 08:00,20:00, blank for spread): ").strip()
        _save_local_settings({
            "uploads_per_day": uploads_per_day,
            "warmup_days": warmup_days,
            "initial_backfill": backfill,
            "upload_schedule": schedule,
        })
        projects = supabase_db.list_projects()
        fields = dict(uploads_per_day=uploads_per_day, warmup_days=warmup_days,
                      initial_backfill=backfill, upload_schedule=schedule)
        if projects:
            supabase_db.update_project(projects[0]["id"], **fields)
        else:
            supabase_db.create_project("Local", **fields)

    print("Step 4/4 — done. Summary:")
    print(f"  channels: {len(config.load_channels())}")
    if not config.is_configured():
        print("  credentials: missing → run `yt-auto oauth`")
    print("  next: `yt-auto status` to check, `yt-auto run` to start the daemon.")
    return 0


def cmd_channels(args):
    import config
    if args.action == "list":
        channels = config.load_channels()
        if not channels:
            print("no channels tracked")
            return 0
        for cid, ch in channels.items():
            print(f"{cid:30} {ch.get('alias', '')}  enabled={ch.get('enabled', True)}")
        return 0
    if args.action == "add":
        ok, res = config.add_channel(args.url, args.alias or "")
        print(res)
        return 0 if ok else 1
    if args.action == "remove":
        ok, res = config.remove_channel(args.channel_id)
        print(res or "removed")
        return 0 if ok else 1
    return 1


def cmd_version(args):
    print(VERSION)
    return 0


# ─── entry point ─────────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="yt-auto",
        description="YT VIDEO AUTOMATION — local-first detect/process/upload bot",
    )
    parser.add_argument("--project", help="project id (defaults to $PROJECT_ID)")
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="run the continuous daemon")
    p_run.add_argument("--once", action="store_true", help="single detect+upload+verify pass")
    p_run.add_argument("--dry-run", action="store_true", help="detect/process but never upload")
    p_run.add_argument("--duration", type=float, help="daemon duration in hours (default 5.5)")

    sub.add_parser("once", help="alias for `run --once`")

    p_status = sub.add_parser("status", help="show current state summary")
    p_status.add_argument("--json", action="store_true")

    p_logs = sub.add_parser("logs", help="show recent upload logs")
    p_logs.add_argument("count", nargs="?", type=int, help="number of entries (default 10)")
    p_logs.add_argument("--json", action="store_true")

    p_verify = sub.add_parser("verify", help="self-verify and heal state")
    p_verify.add_argument("--no-fix", action="store_true", help="report only, no healing")

    sub.add_parser("oauth", help="YouTube OAuth login (get refresh token)")

    sub.add_parser("setup", help="guided first-time configuration")

    p_ch = sub.add_parser("channels", help="manage tracked channels")
    ch_sub = p_ch.add_subparsers(dest="action")
    ch_sub.add_parser("list")
    p_add = ch_sub.add_parser("add")
    p_add.add_argument("url")
    p_add.add_argument("alias", nargs="?", default="")
    p_rm = ch_sub.add_parser("remove")
    p_rm.add_argument("channel_id")

    sub.add_parser("version", help="print version")

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "project", None):
        os.environ["PROJECT_ID"] = args.project
    if getattr(args, "dry_run", False):
        os.environ["INPUT_DRY_RUN"] = "true"

    handlers = {
        "run": cmd_run,
        "once": cmd_run,
        "status": cmd_status,
        "logs": cmd_logs,
        "verify": cmd_verify,
        "oauth": cmd_oauth,
        "setup": cmd_setup,
        "channels": cmd_channels,
        "version": cmd_version,
    }
    if not args.cmd:
        parser.print_help()
        return 1
    if args.cmd == "once":
        args.once = True
    try:
        return handlers[args.cmd](args)
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
