import json
import os
import stat
import tempfile
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".vplink3.0"
CONFIG_PATH = CONFIG_DIR / "config.json"
PROXY_HISTORY_PATH = CONFIG_DIR / "proxy_history.json"
PROXY_BLACKLIST_PATH = CONFIG_DIR / "proxy_blacklist.json"

DEFAULTS = {
    "supabase_url": "",
    "supabase_key": "",
    "supabase_secret": "",
    "proxy_enabled": False,
    "proxy_tier": "premium",
    "youtube_traffic": False,
    "mobile_profile": False,
    "random_urls": [],
    "vnc_port": 5900,
    "views": 1,
}


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_DIR.chmod(0o700)
    except Exception:
        pass


def _write_json_secure(filepath, value):
    _ensure_dir()
    fd, tmp = tempfile.mkstemp(
        dir=str(CONFIG_DIR), prefix=f"{filepath.name}.", suffix=".tmp"
    )
    try:
        os.write(fd, json.dumps(value, indent=2).encode("utf-8"))
        os.close(fd)
        os.chmod(tmp, 0o600)
        os.rename(tmp, str(filepath))
        try:
            filepath.chmod(0o600)
        except Exception:
            pass
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
    _write_json_secure(CONFIG_PATH, merged)
    return merged


def load_proxy_history():
    try:
        raw = PROXY_HISTORY_PATH.read_text("utf-8")
        return json.loads(raw)
    except Exception:
        return {"used": []}


def save_proxy_history(history):
    _write_json_secure(PROXY_HISTORY_PATH, history)


def load_proxy_blacklist():
    twenty_four_h = 24 * 60 * 60 * 1000
    now_ms = int(time.time() * 1000)
    try:
        if PROXY_BLACKLIST_PATH.exists():
            raw = PROXY_BLACKLIST_PATH.read_text("utf-8")
            lst = json.loads(raw)
            filtered = []
            for entry in lst:
                if isinstance(entry, dict):
                    ts = entry.get("ts", 0)
                    if ts == 0 or (now_ms - ts) < twenty_four_h:
                        filtered.append(entry.get("key", ""))
                else:
                    filtered.append(str(entry))
            return filtered
    except Exception:
        pass
    return []


def save_proxy_blacklist(lst):
    _write_json_secure(PROXY_BLACKLIST_PATH, lst)


def add_proxy_blacklist(ip, port):
    twenty_four_h = 24 * 60 * 60 * 1000
    now_ms = int(time.time() * 1000)
    key = f"{ip}:{port}"
    try:
        PROXY_BLACKLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    raw_entries = []
    try:
        if PROXY_BLACKLIST_PATH.exists():
            raw = PROXY_BLACKLIST_PATH.read_text("utf-8")
            raw_entries = json.loads(raw)
    except Exception:
        pass
    filtered = []
    for entry in raw_entries:
        if isinstance(entry, dict):
            k = entry.get("key", "")
        else:
            k = str(entry)
        if k != key:
            filtered.append(entry)
    filtered.append({"key": key, "ts": now_ms})
    pruned = []
    for entry in filtered:
        if isinstance(entry, dict):
            ts = entry.get("ts", 0)
            if ts == 0 or (now_ms - ts) < twenty_four_h:
                pruned.append(entry)
        else:
            pruned.append(entry)
    save_proxy_blacklist(pruned)


def clear_proxy_blacklist():
    save_proxy_blacklist([])


def is_configured():
    cfg = load()
    return bool(cfg.get("supabase_url") and cfg.get("supabase_key") and cfg.get("supabase_secret"))


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--get":
        cfg = load()
        val = cfg.get(args[1], "")
        print(val if val is not None else "")
    elif len(args) >= 3 and args[0] == "--set":
        key = args[1]
        val_str = " ".join(args[2:])
        if val_str == "true":
            val = True
        elif val_str == "false":
            val = False
        elif val_str.isdigit():
            val = int(val_str)
        else:
            val = val_str
        save({key: val})
    elif len(args) == 1 and args[0] == "--check":
        print("configured" if is_configured() else "unconfigured")
    elif len(args) == 0:
        cfg = load()
        print(json.dumps(cfg, indent=2))
    else:
        print(f"Usage: python3 config.py [--get KEY|--set KEY VALUE|--check]", file=sys.stderr)
        sys.exit(1)
