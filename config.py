import json
import os
import tempfile
import time
from pathlib import Path

import supabase_db

DATA_DIR = Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror")))
CONFIG_PATH = DATA_DIR / "config.json"
STATE_PATH = DATA_DIR / "state.json"
ACCOUNTS_PATH = DATA_DIR / "accounts.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

PROJECT_ID = os.environ.get("PROJECT_ID", "")

VERSION = "0.1.0"

DEFAULTS = {
    "yt_client_id": "",
    "yt_client_secret": "",
    "yt_refresh_token": "",
    "shortener_provider": "none",
    "shortener_api_key": "",
    "shortener_api_url": "",
    "mirror_title_prefix": "",
    "mirror_description_suffix": "",
    "custom_title": "",
    "custom_description": "",
    "custom_comment": "",
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
    return {}


def save_channels(channels):
    return


def load_state():
    _ensure_dir()
    try:
        return json.loads(STATE_PATH.read_text("utf-8"))
    except Exception:
        return {"processed": {}, "stats": {"total_mirrored": 0, "total_comments": 0, "total_shortened": 0}}


def save_state(state):
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


PROJECT_FIELD_MAP = {
    "comment_moderation": "comment_moderation",
    "mirror_title_prefix": "mirror_title_prefix",
    "mirror_description_suffix": "mirror_description_suffix",
    "custom_title": "custom_title",
    "custom_description": "custom_description",
    "custom_comment": "custom_comment",
    "shortener_provider": "shortlink_provider",
    "shortener_api_key": "shortlink_api_key",
}


def load_tui_settings():
    defaults = {
        "active_account": "",
        "comment_text": "Download: {url}",
        "mirror_title_prefix": "",
        "mirror_description_suffix": "",
        "custom_title": "",
        "custom_description": "",
        "custom_comment": "",
        "privacy_status": "public",
        "category_id": "22",
        "shortener_api_key": "",
        "shortener_api_url": "",
        "shortener_provider": "vplink",
        "comment_moderation": "heldForReview",
    }
    if supabase_db.is_enabled():
        if PROJECT_ID:
            project = supabase_db.get_project(PROJECT_ID)
            if project:
                merged = {**defaults}
                for key, col in PROJECT_FIELD_MAP.items():
                    if project.get(col) is not None:
                        merged[key] = project[col]
                return merged
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
