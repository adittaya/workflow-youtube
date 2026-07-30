import json
import os
import tempfile
import time
from pathlib import Path

import supabase_db

DATA_DIR = Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror")))
CONFIG_PATH = DATA_DIR / "config.json"
CHANNELS_PATH = DATA_DIR / "channels.json"
STATE_PATH = DATA_DIR / "state.json"
ACCOUNTS_PATH = DATA_DIR / "accounts.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

PROJECT_ID = os.environ.get("PROJECT_ID", "")

DEFAULTS = {
    "yt_client_id": "",
    "yt_client_secret": "",
    "yt_refresh_token": "",
    "shortener_provider": "none",
    "shortener_api_key": "",
    "shortener_api_url": "",
    "check_interval_minutes": 15,
    "mirror_title_prefix": "",
    "mirror_description_suffix": "",
    "comment_text": "Download link: {url}",
    "privacy_status": "public",
    "category_id": "22",
    "dry_run": False,
}


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        DATA_DIR.chmod(0o700)
    except Exception:
        pass


def _write_json(filepath, value):
    _ensure_dir()
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), prefix=f"{filepath.name}.", suffix=".tmp")
    try:
        os.write(fd, json.dumps(value, indent=2).encode("utf-8"))
        os.close(fd)
        os.chmod(tmp, 0o600)
        os.rename(tmp, str(filepath))
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def load():
    _ensure_dir()
    try:
        raw = CONFIG_PATH.read_text("utf-8")
        saved = json.loads(raw)
        merged = {**DEFAULTS, **saved}
        return merged
    except Exception:
        return {**DEFAULTS}


def save(config):
    existing = load()
    merged = {**existing, **config}
    _write_json(CONFIG_PATH, merged)
    return merged


def load_channels():
    if supabase_db.is_enabled() and not PROJECT_ID:
        rows = supabase_db.get_all_channels()
        return {r["id"]: {
            "url": r.get("url", ""),
            "alias": r.get("name", r["id"]),
            "added_at": r.get("added_at", ""),
            "enabled": r.get("enabled", True),
        } for r in rows}
    _ensure_dir()
    try:
        return json.loads(CHANNELS_PATH.read_text("utf-8"))
    except Exception:
        return {}


def save_channels(channels):
    if supabase_db.is_enabled() and not PROJECT_ID:
        for ch_id, ch in channels.items():
            supabase_db.save_channel(ch_id, {
                "name": ch.get("alias", ch_id),
                "url": ch.get("url", ""),
                "enabled": ch.get("enabled", True),
                "added_at": ch.get("added_at"),
            })
        return
    _ensure_dir()
    _write_json(CHANNELS_PATH, channels)


def load_state():
    if supabase_db.is_enabled():
        pid = PROJECT_ID
        processed_rows = supabase_db.get_all_mirror_states(project_id=pid)
        stats = supabase_db.get_mirror_stats(project_id=pid)
        processed = {}
        for r in processed_rows:
            key = f"{r['source_channel']}:{r['source_video_id']}"
            processed[key] = {
                "new_video_id": r.get("mirrored_video_id") or "",
                "original_title": r.get("original_title", ""),
                "mirrored_at": r.get("mirrored_at") or "",
                "comment_id": r.get("comment_id", ""),
                "shortened_urls": r.get("shortened_urls") or {},
            }
        return {"processed": processed, "stats": stats}
    _ensure_dir()
    try:
        return json.loads(STATE_PATH.read_text("utf-8"))
    except Exception:
        return {"processed": {}, "stats": {"total_mirrored": 0, "total_comments": 0, "total_shortened": 0}}


def save_state(state):
    if supabase_db.is_enabled():
        pid = PROJECT_ID
        for key, entry in state.get("processed", {}).items():
            if ":" in key:
                source, vid = key.split(":", 1)
            else:
                source, vid = key, ""
            supabase_db.save_mirror_state(source, vid, {
                "mirrored_video_id": entry.get("new_video_id") or entry.get("mirrored_video_id"),
                "original_title": entry.get("original_title", ""),
                "mirrored_at": entry.get("mirrored_at"),
                "comment_id": entry.get("comment_id", ""),
                "shortened_urls": entry.get("shortened_urls", {}),
            }, project_id=pid)
        supabase_db.update_mirror_stats(state.get("stats", {}), project_id=pid)
        return
    _ensure_dir()
    _write_json(STATE_PATH, state)


def load_accounts():
    if supabase_db.is_enabled() and not PROJECT_ID:
        rows = supabase_db.get_all_accounts()
        return {r["name"]: {
            "client_id": r["client_id"],
            "client_secret": r["client_secret"],
            "refresh_token": r["refresh_token"],
            "channel_id": r.get("channel_id", ""),
            "channel_name": r.get("channel_name", ""),
        } for r in rows}
    _ensure_dir()
    try:
        return json.loads(ACCOUNTS_PATH.read_text("utf-8"))
    except Exception:
        return {}


def save_accounts(accounts):
    if supabase_db.is_enabled() and not PROJECT_ID:
        for name, acct in accounts.items():
            supabase_db.save_account(name, {
                "client_id": acct.get("client_id", ""),
                "client_secret": acct.get("client_secret", ""),
                "refresh_token": acct.get("refresh_token", ""),
                "channel_id": acct.get("channel_id", ""),
                "channel_name": acct.get("channel_name", ""),
            })
        return
    _ensure_dir()
    _write_json(ACCOUNTS_PATH, accounts)


def load_tui_settings():
    defaults = {
        "active_account": "",
        "active_github": "",
        "comment_text": "Download: {url}",
        "mirror_title_prefix": "",
        "mirror_description_suffix": "",
        "privacy_status": "public",
        "category_id": "22",
        "shortener_api_key": "",
        "shortener_api_url": "",
        "check_interval_minutes": 15,
        "max_per_cycle": 3,
        "shortener_provider": "vplink",
        "comment_moderation": "heldForReview",
        "warmup_days": 0,
        "uploads_per_day": 2,
        "initial_backfill": 5,
    }
    if supabase_db.is_enabled() and not PROJECT_ID:
        for key in defaults:
            val = supabase_db.get_setting(f"tui_{key}")
            if val is not None:
                defaults[key] = val
        return defaults
    _ensure_dir()
    try:
        saved = json.loads(SETTINGS_PATH.read_text("utf-8"))
        return {**defaults, **saved}
    except Exception:
        return defaults


def get_yt_credentials():
    env_client_id = os.environ.get("YT_CLIENT_ID", "")
    env_client_secret = os.environ.get("YT_CLIENT_SECRET", "")
    env_refresh_token = os.environ.get("YT_REFRESH_TOKEN", "")
    if env_client_id and env_client_secret and env_refresh_token:
        return {
            "client_id": env_client_id,
            "client_secret": env_client_secret,
            "refresh_token": env_refresh_token,
        }
    accounts = load_accounts()
    tui_settings = load_tui_settings()
    active = tui_settings.get("active_account")
    if active and active in accounts:
        acct = accounts[active]
        return {
            "client_id": acct["client_id"],
            "client_secret": acct["client_secret"],
            "refresh_token": acct["refresh_token"],
        }
    cfg = load()
    return {
        "client_id": cfg.get("yt_client_id", ""),
        "client_secret": cfg.get("yt_client_secret", ""),
        "refresh_token": cfg.get("yt_refresh_token", ""),
    }


def get_active_account_name():
    tui_settings = load_tui_settings()
    return tui_settings.get("active_account", "")


def is_configured():
    creds = get_yt_credentials()
    return bool(creds["client_id"] and creds["client_secret"] and creds["refresh_token"])


def add_channel(url, alias=""):
    channels = load_channels()
    channel_id = _extract_channel_id(url)
    if not channel_id:
        return False, "Invalid channel URL — use @handle or channel ID"
    if channel_id in channels:
        return False, "Channel already tracked"
    channels[channel_id] = {
        "url": url,
        "alias": alias or channel_id,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "enabled": True,
    }
    save_channels(channels)
    return True, channel_id


def remove_channel(channel_id):
    channels = load_channels()
    if channel_id not in channels:
        return False, "Channel not found"
    del channels[channel_id]
    save_channels(channels)
    return True, None


def _extract_channel_id(url):
    url = url.strip()
    if "/channel/" in url:
        return url.split("/channel/")[-1].split("/")[0].split("?")[0]
    if "@" in url:
        handle = url.split("@")[-1].split("/")[0].split("?")[0]
        return f"@{handle}"
    if url.startswith("UC") and len(url) > 20:
        return url
    if "youtube.com" in url and "/c/" in url:
        return url.split("/c/")[-1].split("/")[0].split("?")[0]
    return url


def log(msg):
    elapsed = time.time() - _start_time if _start_time else 0
    print(f"  [{elapsed:.1f}s] {msg}")


_start_time = time.time()


def set_start_time(t):
    global _start_time
    _start_time = t


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--get":
        cfg = load()
        print(cfg.get(args[1], ""))
    elif len(args) >= 3 and args[0] == "--set":
        key = args[1]
        val = " ".join(args[2:])
        if val == "true":
            val = True
        elif val == "false":
            val = False
        elif val.isdigit():
            val = int(val)
        save({key: val})
    elif len(args) == 1 and args[0] == "--check":
        print("configured" if is_configured() else "unconfigured")
    elif len(args) == 0:
        print(json.dumps(load(), indent=2))
    else:
        print("Usage: python3 config.py [--get KEY|--set KEY VALUE|--check]")
        sys.exit(1)
