#!/usr/bin/env python3
"""yt-auto — YT VIDEO AUTOMATION command-line interface (local-first).

Manual link → process → upload tool. Paste a YouTube URL, it runs the
Demucs → FFmpeg → BGM pipeline and uploads to your channel. All state is
backed by local JSON files under ~/.yt-mirror/ when Supabase is not
configured.

    yt-auto upload URL          interactive single upload: link → process →
                                title/comment/description prompts → publish
    yt-auto setup               guided first-time configuration
    yt-auto oauth               YouTube OAuth login (get refresh token)
    yt-auto status [--json]     current state summary
    yt-auto logs [N] [--json]   recent upload log entries
    yt-auto verify [--no-fix]   self-verification of state
    yt-auto version
"""
import argparse
import json
import os
import sys
import time

import config

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

VERSION = config.VERSION


def _import_backend():
    import config
    import supabase_db
    import daily_uploader
    import verify_state
    return config, supabase_db, daily_uploader, verify_state


def _pid(args):
    return os.environ.get("PROJECT_ID", getattr(args, "project", "") or "")


# ─── commands ────────────────────────────────────────────────────────────

def cmd_status(args):
    import supabase_db
    import daily_uploader
    pid = _pid(args)

    # Any CLI touchpoint drains queued comments for scheduled uploads whose
    # publish time has passed (also runs on TUI startup and `comments`).
    posted, dropped = 0, 0
    try:
        posted, dropped = daily_uploader.drain_pending_comments()
    except Exception:
        pass

    status = daily_uploader.get_status()
    try:
        alerts = supabase_db.get_open_alerts(project_id=pid, limit=10)
    except Exception:
        alerts = []

    if args.json:
        print(json.dumps({
            "mode": "supabase" if supabase_db.is_enabled() else "local",
            "project_id": pid,
            **{k: status.get(k) for k in (
                "total_uploaded", "last_upload", "processed_count")},
            "open_alerts": len(alerts),
        }, indent=2))
        return 0

    print(f"yt-auto {VERSION} — mode: {'supabase (cloud)' if supabase_db.is_enabled() else 'local JSON files'}")
    print(f"project: {pid or '(default)'}")
    print(f"total uploaded: {status['total_uploaded']}  (last: {status['last_upload'] or 'never'})")
    print(f"processed: {status['processed_count']}")
    if posted or dropped:
        print(f"queued comments: {posted} posted, {dropped} dropped")
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
    import verify_state
    import daily_uploader
    # Any CLI touchpoint drains the queued comments for scheduled uploads
    # whose publish time has passed (also runs on TUI startup and `comments`).
    try:
        daily_uploader.drain_pending_comments()
    except Exception:
        pass
    pid = _pid(args)
    res = verify_state.run_for(pid, owner=f"cli-{time.time():.0f}", fix=not args.no_fix)
    return 1 if res["fails"] else 0


def cmd_oauth(args):
    import config
    config.apply_proxy_env()
    cfg = config.load()
    cid = os.environ.get("YT_CLIENT_ID", "") or cfg.get("yt_client_id", "")
    csec = os.environ.get("YT_CLIENT_SECRET", "") or cfg.get("yt_client_secret", "")
    cid = config.sanitize_client_id(cid)
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


def _prompt(text):
    try:
        return input(text).strip()
    except EOFError:
        print()
        return ""


def cmd_setup(args):
    import config

    cfg = config.load()
    if not cfg.get("yt_client_id") or not cfg.get("yt_client_secret"):
        print("Step 1/2 — YouTube API credentials (https://console.cloud.google.com/apis/credentials)")
        cid = config.sanitize_client_id(_prompt("OAuth Client ID: "))
        csec = _prompt("OAuth Client Secret: ")
        if cid and csec:
            config.save({"yt_client_id": cid, "yt_client_secret": csec})
    if not config.is_configured():
        print("  → next run `yt-auto oauth` to get a refresh token.")

    print("Step 2/2 — done. Summary:")
    if not config.is_configured():
        print("  credentials: missing → run `yt-auto oauth`")
    print("  next: `yt-auto upload URL` to process and upload a video.")
    return 0


def cmd_upload(args):
    """Interactive single-video upload: paste a link, process it through the
    Demucs → FFmpeg → BGM pipeline, then prompt for a custom title, comment and
    description (Enter copies from the source video; comment Enter = skip) and
    a publish confirmation."""
    import re
    import shutil

    import config
    import daily_uploader
    import download_helpers
    import youtube_api

    url = args.url
    m = re.search(r'(?:v=|youtu\.be/|youtube\.com/embed/)([\w-]{11})', url)
    if not m:
        print("Invalid YouTube URL")
        return 1
    video_id = m.group(1)
    source_url = f"https://www.youtube.com/watch?v={video_id}"

    if not config.is_configured():
        print("YouTube credentials not configured — run `yt-auto oauth` first.")
        return 1

    config.apply_proxy_env()

    try:
        youtube = youtube_api.get_client()
        details = youtube_api.get_video_details(youtube, video_id)
    except Exception as e:
        print(f"could not fetch video info: {e}")
        return 1
    if not details:
        print("video not found")
        return 1
    source_title = details.get("title", "")
    source_tags = details.get("tags", [])
    source_channel = details.get("channel_id", "")

    print(f"\nsource: {source_title}\n")

    print("downloading...")
    try:
        result = download_helpers.download_video(source_url)
    except download_helpers.YouTubeBotCheck:
        print("download blocked by YouTube bot-check — the proxy IP is flagged.")
        print("fix: set YT_COOKIES / YT_COOKIES_FILE (cookies.txt from a logged-in "
              "browser) or use a residential proxy, then retry.")
        return 1
    if not result:
        print("download failed")
        return 1
    video_path = result["path"]
    download_dir = os.path.dirname(video_path)
    try:
        print("processing (Demucs vocal separation → FFmpeg edits → BGM mix)...")
        processed = daily_uploader.process_video(video_path)
        if not processed:
            print("processing failed")
            return 1
        print(f"processed: {os.path.basename(processed)}\n")

        title = _prompt(f"Title (Enter = copy from source) [{source_title}]") or source_title
        comment = _prompt("Comment (Enter = no comment; or paste a custom one)")
        desc = _prompt("Description (Enter = copy from source)")
        publish = _prompt("Publish now? (Y/n)").strip().lower()
        print()

        publish = publish in ("", "y", "yes")
        privacy = "public" if publish else "private"
        vid = daily_uploader.upload_daily(
            processed, title=title, description=desc or None, tags=source_tags,
            source_url=source_url, force=True, source_channel=source_channel,
            comment=comment or daily_uploader.SKIP_COMMENT, raw=True,
            privacy_status=privacy, details=details,
        )
        if vid:
            state = "published" if publish else "saved as private draft"
            print(f"{state}: https://www.youtube.com/watch?v={vid}")
            return 0
        print("upload failed")
        return 1
    finally:
        try:
            shutil.rmtree(download_dir, ignore_errors=True)
            print(f"cleaned up: {download_dir}")
        except Exception as e:
            config.log(f"cleanup failed: {e}")


def cmd_comments(args):
    import daily_uploader
    posted, dropped = daily_uploader.drain_pending_comments()
    print(f"queued comments: {posted} posted, {dropped} dropped, "
          f"{len(daily_uploader.supabase_db.list_pending_comments())} still waiting")
    return 0


def cmd_proxy(args):
    import json as _json
    import proxy_pool
    if args.action == "status":
        summary = proxy_pool.pool_summary()
        if args.json:
            print(_json.dumps(summary, indent=2, default=str))
            return 0
        if not summary.get("configured"):
            print(f"proxy pool not configured (message: {summary.get('message')})")
            return 1
        print(f"pool:      {'ON' if summary.get('enabled') else 'OFF'}")
        print("configured: yes")
        print(f"total:     {summary.get('total', 0)}")
        print(f"alive:     {summary.get('alive', 0)}")
        best = summary.get("best")
        if best:
            print(f"fastest:   {best['ip']}:{best.get('port')} ({best.get('latency_ms')}ms)")
        else:
            print("fastest:   none working")
        active = summary.get("active")
        if active:
            print(f"active:    {active['ip']}:{active.get('port')} ({active.get('latency_ms')}ms)")
        else:
            print("active:    none (run `yt-auto proxy refresh`)")
        return 0
    if args.action == "refresh":
        if not proxy_pool.is_configured():
            print("proxy pool not configured — set PROXY_POOL_URL / PROXY_POOL_KEY")
            return 1

        def progress(done, total, label):
            print(f"\r  tested {done}/{total} — {label}{' ' * 20}", end="", flush=True)

        print("refreshing & testing proxy pool...")
        best, msg = proxy_pool.refresh_and_activate(progress=progress)
        print()
        if best:
            proxy_pool.enable()
        print(msg)
        return 0 if best else 1
    return 1


def cmd_version(args):
    print(VERSION)
    return 0


# ─── entry point ─────────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="yt-auto",
        description="YT VIDEO AUTOMATION — local-first manual upload tool",
    )
    parser.add_argument("--project", help="project id (defaults to $PROJECT_ID)")
    sub = parser.add_subparsers(dest="cmd")

    p_status = sub.add_parser("status", help="show current state summary")
    p_status.add_argument("--json", action="store_true")

    p_logs = sub.add_parser("logs", help="show recent upload logs")
    p_logs.add_argument("count", nargs="?", type=int, help="number of entries (default 10)")
    p_logs.add_argument("--json", action="store_true")

    p_verify = sub.add_parser("verify", help="self-verify and heal state")
    p_verify.add_argument("--no-fix", action="store_true", help="report only, no healing")

    sub.add_parser("oauth", help="YouTube OAuth login (get refresh token)")

    sub.add_parser("setup", help="guided first-time configuration")

    p_upload = sub.add_parser("upload", help="interactive single upload (link → process → prompts → publish)")
    p_upload.add_argument("url", help="YouTube URL to process and upload")

    sub.add_parser("version", help="print version")

    sub.add_parser("comments", help="post queued comments for scheduled uploads that have published")

    p_proxy = sub.add_parser("proxy", help="proxy pool: refresh (test+activate) or status")
    p_proxy.add_argument("action", choices=["refresh", "status"], help="what to do")
    p_proxy.add_argument("--json", action="store_true", help="JSON output (status)")

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "project", None):
        os.environ["PROJECT_ID"] = args.project

    handlers = {
        "status": cmd_status,
        "logs": cmd_logs,
        "verify": cmd_verify,
        "oauth": cmd_oauth,
        "setup": cmd_setup,
        "upload": cmd_upload,
        "version": cmd_version,
        "proxy": cmd_proxy,
        "comments": cmd_comments,
    }
    if not args.cmd:
        parser.print_help()
        return 1
    try:
        return handlers[args.cmd](args)
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
