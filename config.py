import json
import os
import tempfile
import time
from pathlib import Path

import supabase_db

DATA_DIR = Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror")))
CONFIG_PATH = DATA_DIR / "config.json"
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
        "fps": 20,
        "trim_start": 20,
        "trim_end": 10,
        "bgm_source": "yt_link",
        "bgm_yt_url": "",
        "bgm_dir": "",
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


def save_tui_setting(key, value):
    """Persist a TUI setting in the format load_tui_settings() reads back:
    plain key in local settings.json, `tui_<key>` in the Supabase settings
    table (mirrors the tui_ prefix load_tui_settings uses in cloud mode)."""
    if supabase_db.is_enabled() and not PROJECT_ID:
        supabase_db.set_setting(f"tui_{key}", value)
    else:
        supabase_db.set_setting(key, value)


def save_tui_settings(**fields):
    for key, value in fields.items():
        save_tui_setting(key, value)


PROXY_DEFAULTS = {
    "proxy_enabled": False,
    "proxy_protocol": "http",
    "proxy_host": "",
    "proxy_port": "",
    "proxy_username": "",
    "proxy_password": "",
    "proxy_pool_enabled": False,
    "proxy_pool_url": "",
    "proxy_pool_key": "",
    "proxy_active_ip": "",
    "proxy_active_port": "",
    "proxy_active_proto": "http",
    "proxy_active_latency": 0,
    "proxy_picked_at": "",
}


def get_proxy_settings():
    """Proxy config from the settings store (local settings.json or the
    Supabase settings table). Identical behaviour in both modes."""
    out = dict(PROXY_DEFAULTS)
    for key in out:
        val = supabase_db.get_setting(key, None)
        if val is not None:
            out[key] = val
    return out


def save_proxy_settings(**fields):
    for key, val in fields.items():
        supabase_db.set_setting(key, val)


def get_proxy_url():
    """Full proxy URL like http://user:pass@host:port, or '' when disabled."""
    s = get_proxy_settings()
    if not s.get("proxy_enabled"):
        return ""
    host = str(s.get("proxy_host", "") or "").strip()
    if not host:
        return ""
    scheme = str(s.get("proxy_protocol", "") or "http").strip() or "http"
    port = str(s.get("proxy_port", "") or "").strip()
    user = str(s.get("proxy_username", "") or "").strip()
    pwd = str(s.get("proxy_password", "") or "").strip()
    netloc = host + (f":{port}" if port else "")
    if user:
        netloc = f"{user}" + (f":{pwd}" if pwd else "") + "@" + netloc
    return f"{scheme}://{netloc}"


def mask_proxy_url(url):
    """Return a display-safe proxy URL with the password masked."""
    if not url:
        return ""
    from urllib.parse import urlsplit, urlunsplit
    try:
        parts = urlsplit(url)
        if parts.username is not None:
            host = parts.hostname or ""
            port = f":{parts.port}" if parts.port else ""
            netloc = f"{parts.username}:***@{host}{port}"
            return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        pass
    return url


def apply_proxy_env():
    """Set (or clear) HTTP(S)_PROXY / ALL_PROXY env vars so stdlib urllib,
    requests and yt-dlp all route through the configured proxy. Returns the
    proxy URL ('' when disabled)."""
    url = get_proxy_url()
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        if url:
            os.environ[key] = url
        else:
            os.environ.pop(key, None)
    if url:
        no_proxy = os.environ.get("no_proxy", os.environ.get("NO_PROXY", ""))
        if "127.0.0.1" not in no_proxy and "localhost" not in no_proxy:
            no_proxy = (no_proxy + "," if no_proxy else "") + "127.0.0.1,localhost"
            os.environ["no_proxy"] = no_proxy
            os.environ["NO_PROXY"] = no_proxy
    return url


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


def is_configured():
    creds = get_yt_credentials()
    return bool(creds["client_id"] and creds["client_secret"] and creds["refresh_token"])


def log(msg):
    elapsed = time.time() - _start_time if _start_time else 0
    print(f"  [{elapsed:.1f}s] {msg}")


_start_time = time.time()


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
