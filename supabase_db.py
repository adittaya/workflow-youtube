import os
import json
from datetime import datetime

_SUPABASE_URL = None
_SUPABASE_KEY = None
_DB_ENABLED = False


def configure(url=None, key=None):
    global _SUPABASE_URL, _SUPABASE_KEY, _DB_ENABLED
    _SUPABASE_URL = url or os.environ.get("SUPABASE_URL", "")
    _SUPABASE_KEY = key or os.environ.get("SUPABASE_SERVICE_KEY", "")
    _DB_ENABLED = bool(_SUPABASE_URL and _SUPABASE_KEY)


def is_enabled():
    return _DB_ENABLED


def _headers():
    return {
        "apikey": _SUPABASE_KEY,
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _api(path):
    return f"{_SUPABASE_URL.rstrip('/')}/rest/v1/{path.lstrip('/')}"


def _request(method, path, **kwargs):
    import urllib.request
    import urllib.error
    url = _api(path)
    data = kwargs.pop("data", None)
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 406 and method == "GET":
            return None
        raise


def _upsert(table, data, on_conflict="id"):
    result = _request("POST", table + f"?on_conflict={on_conflict}", data=data)
    return result


# ─── Settings ────────────────────────────────────────────────────────────

def get_setting(key, default=None):
    row = _request("GET", f"settings?key=eq.{key}&select=value")
    if row:
        val = row[0]["value"]
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return val
        return val
    return default


def set_setting(key, value):
    if not isinstance(value, str):
        value = json.dumps(value)
    _upsert("settings", {"key": key, "value": value, "updated_at": datetime.utcnow().isoformat()})


def get_all_settings():
    rows = _request("GET", "settings?select=key,value")
    return {r["key"]: r["value"] for r in rows} if rows else {}


# ─── Accounts ────────────────────────────────────────────────────────────

def get_account(name):
    row = _request("GET", f"accounts?name=eq.{name}&select=*")
    return row[0] if row else None


def get_all_accounts():
    return _request("GET", "accounts?select=*") or []


def save_account(name, data):
    data["name"] = name
    data["updated_at"] = datetime.utcnow().isoformat()
    _upsert("accounts", data, on_conflict="name")


def delete_account(name):
    _request("DELETE", f"accounts?name=eq.{name}")


# ─── Channels ────────────────────────────────────────────────────────────

def get_channel(channel_id):
    row = _request("GET", f"channels?id=eq.{channel_id}&select=*")
    return row[0] if row else None


def get_all_channels():
    return _request("GET", "channels?select=*") or []


def save_channel(channel_id, data):
    data["id"] = channel_id
    data["updated_at"] = datetime.utcnow().isoformat()
    _upsert("channels", data, on_conflict="id")


def delete_channel(channel_id):
    _request("DELETE", f"channels?id=eq.{channel_id}")


# ─── Mirror State ────────────────────────────────────────────────────────

def get_mirror_state(source_channel, source_video_id):
    row = _request("GET",
        f"mirror_state?source_channel=eq.{source_channel}&source_video_id=eq.{source_video_id}&select=*")
    return row[0] if row else None


def get_all_mirror_states():
    return _request("GET", "mirror_state?select=*") or []


def save_mirror_state(source_channel, source_video_id, data):
    data["source_channel"] = source_channel
    data["source_video_id"] = source_video_id
    data["mirrored_at"] = data.get("mirrored_at") or datetime.utcnow().isoformat()
    _upsert("mirror_state", data, on_conflict="source_channel,source_video_id")


# ─── Mirror Stats ────────────────────────────────────────────────────────

def get_mirror_stats():
    row = _request("GET", "mirror_stats?id=eq.1&select=*")
    if row:
        return row[0]
    return {"total_mirrored": 0, "total_comments": 0, "total_shortened": 0}


def update_mirror_stats(stats):
    stats["id"] = 1
    stats["updated_at"] = datetime.utcnow().isoformat()
    _upsert("mirror_stats", stats, on_conflict="id")


# ─── Upload State ────────────────────────────────────────────────────────

def get_upload_state():
    row = _request("GET", "upload_state?id=eq.1&select=*")
    if row:
        s = row[0]
        if isinstance(s.get("processed_hashes"), list):
            s["processed_hashes"] = [h for h in s["processed_hashes"]]
        return s
    return {
        "account_created": None, "warmup_start": None,
        "warmup_complete": False, "first_upload_date": None,
        "total_uploaded": 0, "last_upload_date": None,
        "last_upload_hour": None, "processed_hashes": [],
        "yt_client_id": "",
    }


def save_upload_state(state):
    row = {
        "id": 1,
        "account_created": state.get("account_created"),
        "warmup_start": state.get("warmup_start"),
        "warmup_complete": state.get("warmup_complete", False),
        "first_upload_date": state.get("first_upload_date"),
        "total_uploaded": state.get("total_uploaded", 0),
        "last_upload_date": state.get("last_upload_date"),
        "last_upload_hour": state.get("last_upload_hour"),
        "processed_hashes": state.get("processed_hashes", []),
        "yt_client_id": state.get("yt_client_id", ""),
        "updated_at": datetime.utcnow().isoformat(),
    }
    _upsert("upload_state", row, on_conflict="id")


# ─── Upload Logs ─────────────────────────────────────────────────────────

def get_upload_logs(limit=100):
    return _request("GET", f"upload_logs?select=*&order=upload_time.desc&limit={limit}") or []


def get_today_upload_count(date_str):
    rows = _request("GET",
        f"upload_logs?select=id&upload_date=eq.{date_str}")
    return len(rows) if rows else 0


def add_upload_log(entry):
    _request("POST", "upload_logs", data=entry)


# ─── Channel Cursors (monitor state) ───────────────────────────────────

def get_channel_cursor(channel_id):
    row = _request("GET", f"channel_cursors?channel_id=eq.{channel_id}&select=*")
    return row[0] if row else None


def get_all_cursors():
    rows = _request("GET", "channel_cursors?select=*")
    result = {}
    for r in rows or []:
        result[r["channel_id"]] = r
    return result


def save_channel_cursor(channel_id, data):
    data["channel_id"] = channel_id
    data["updated_at"] = datetime.utcnow().isoformat()
    _upsert("channel_cursors", data, on_conflict="channel_id")


# ─── Init ────────────────────────────────────────────────────────────────

configure()
