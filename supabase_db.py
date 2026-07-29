import os
import json
import time
import urllib.error
from datetime import datetime, timezone

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
        "Prefer": "return=representation,resolution=merge-duplicates",
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
    max_retries = kwargs.get("retries", 3)
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 406 and method == "GET":
                return None
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                import sys
                print(f"supabase retry {attempt + 1}/{max_retries} after {wait}s: {e}", file=sys.stderr)
                time.sleep(wait)
                continue
            raise


def _upsert(table, data, on_conflict="id"):
    try:
        return _request("POST", table + f"?on_conflict={on_conflict}", data=data)
    except urllib.error.HTTPError as e:
        if e.code == 409:
            key_cols = [c.strip() for c in on_conflict.split(",")]
            key_filter = "&".join(f"{k}=eq.{data.get(k)}" for k in key_cols if data.get(k) is not None)
            if key_filter:
                existing = _request("GET", f"{table}?{key_filter}&select={key_cols[0]}")
                if existing:
                    return _request("PATCH", f"{table}?{key_filter}", data=data)
            return _request("POST", table, data=data)
        raise


def get_pending_hashes(project_id="1"):
    val = get_setting(f"pending_hashes_{project_id}", [])
    return val if isinstance(val, list) else []


def set_pending_hashes(hashes, project_id="1"):
    if not isinstance(hashes, list):
        hashes = []
    set_setting(f"pending_hashes_{project_id}", hashes)


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
    _upsert("settings", {"key": key, "value": value, "updated_at": datetime.now(timezone.utc).isoformat()}, on_conflict="key")


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
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
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
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _upsert("channels", data, on_conflict="id")


def delete_channel(channel_id):
    _request("DELETE", f"channels?id=eq.{channel_id}")


# ─── Mirror State ────────────────────────────────────────────────────────

def get_mirror_state(source_channel, source_video_id, project_id=""):
    row = _request("GET",
        f"mirror_state?project_id=eq.{project_id}&source_channel=eq.{source_channel}&source_video_id=eq.{source_video_id}&select=*")
    return row[0] if row else None


def get_all_mirror_states(project_id=""):
    return _request("GET", f"mirror_state?project_id=eq.{project_id}&select=*") or []


def save_mirror_state(source_channel, source_video_id, data, project_id=""):
    data["project_id"] = project_id
    data["source_channel"] = source_channel
    data["source_video_id"] = source_video_id
    data["mirrored_at"] = data.get("mirrored_at") or datetime.now(timezone.utc).isoformat()
    _upsert("mirror_state", data, on_conflict="project_id,source_channel,source_video_id")


# ─── Mirror Stats ────────────────────────────────────────────────────────

def get_mirror_stats(project_id=""):
    row = _request("GET", f"mirror_stats?project_id=eq.{project_id}&select=*")
    if row:
        return row[0]
    return {"total_mirrored": 0, "total_comments": 0, "total_shortened": 0}


def update_mirror_stats(stats, project_id=""):
    stats["project_id"] = project_id
    stats["updated_at"] = datetime.now(timezone.utc).isoformat()
    _upsert("mirror_stats", stats, on_conflict="project_id")


# ─── Upload State ────────────────────────────────────────────────────────

def get_upload_state(project_id=""):
    row = _request("GET", f"upload_state?project_id=eq.{project_id}&select=*")
    if row:
        s = row[0]
        if isinstance(s.get("processed_hashes"), list):
            s["processed_hashes"] = [h for h in s["processed_hashes"]]
        if isinstance(s.get("pending_hashes"), list):
            s["pending_hashes"] = [h for h in s["pending_hashes"]]
        return s
    return {
        "project_id": project_id,
        "account_created": None, "warmup_start": None,
        "warmup_complete": False, "first_upload_date": None,
        "total_uploaded": 0, "last_upload_date": None,
        "last_upload_hour": None, "processed_hashes": [],
        "pending_hashes": [],
        "yt_client_id": "",
    }


def save_upload_state(state, project_id=""):
    row = {
        "project_id": project_id,
        "account_created": state.get("account_created"),
        "warmup_start": state.get("warmup_start"),
        "warmup_complete": state.get("warmup_complete", False),
        "first_upload_date": state.get("first_upload_date"),
        "total_uploaded": state.get("total_uploaded", 0),
        "last_upload_date": state.get("last_upload_date"),
        "last_upload_hour": state.get("last_upload_hour"),
        "processed_hashes": state.get("processed_hashes", []),
        "pending_hashes": state.get("pending_hashes", []),
        "yt_client_id": state.get("yt_client_id", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _upsert("upload_state", row, on_conflict="project_id")


# ─── Upload Logs ─────────────────────────────────────────────────────────

def get_upload_logs(limit=100, project_id=""):
    return _request("GET", f"upload_logs?select=*&project_id=eq.{project_id}&order=upload_time.desc&limit={limit}") or []


def get_today_upload_count(date_str, project_id=""):
    rows = _request("GET",
        f"upload_logs?select=id&project_id=eq.{project_id}&upload_date=eq.{date_str}")
    return len(rows) if rows else 0


def add_upload_log(entry, project_id=""):
    entry["project_id"] = project_id
    _request("POST", "upload_logs", data=entry)


# ─── Channel Cursors (monitor state) ───────────────────────────────────

def get_channel_cursor(channel_id, project_id=""):
    row = _request("GET", f"channel_cursors?project_id=eq.{project_id}&channel_id=eq.{channel_id}&select=*")
    return row[0] if row else None


def get_all_cursors(project_id=""):
    rows = _request("GET", f"channel_cursors?project_id=eq.{project_id}&select=*")
    result = {}
    for r in rows or []:
        result[r["channel_id"]] = r
    return result


def save_channel_cursor(channel_id, data, project_id=""):
    data["project_id"] = project_id
    data["channel_id"] = channel_id
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _upsert("channel_cursors", data, on_conflict="project_id,channel_id")


# ─── Projects ───────────────────────────────────────────────────────────────

def list_projects():
    rows = _request("GET", "projects?select=*&order=name.asc")
    return rows or []


def get_project(project_id):
    row = _request("GET", f"projects?id=eq.{project_id}&select=*")
    return row[0] if row else None


def create_project(name, **fields):
    data = {"name": name}
    for k, v in fields.items():
        if v is not None:
            data[k] = v
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = _request("POST", "projects", data=data)
    if isinstance(result, list) and len(result) > 0:
        return result[0]
    return result


def update_project(project_id, **fields):
    data = {"updated_at": datetime.now(timezone.utc).isoformat()}
    for k, v in fields.items():
        if v is not None:
            data[k] = v
    _request("PATCH", f"projects?id=eq.{project_id}", data=data)
    return get_project(project_id)


def delete_project(project_id):
    _request("DELETE", f"projects?id=eq.{project_id}")


# ─── Init ────────────────────────────────────────────────────────────────

configure()
