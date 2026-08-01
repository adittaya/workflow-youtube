import os
import json
import time
import tempfile
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone, timedelta

_SUPABASE_URL = None
_SUPABASE_KEY = None
_DB_ENABLED = False


def configure(url=None, key=None):
    global _SUPABASE_URL, _SUPABASE_KEY, _DB_ENABLED
    _SUPABASE_URL = url or os.environ.get("SUPABASE_URL", "")
    _SUPABASE_KEY = key or os.environ.get("SUPABASE_SERVICE_KEY", "")
    _DB_ENABLED = bool(_SUPABASE_URL and _SUPABASE_KEY)


def disable():
    """Force local mode, ignoring SUPABASE_URL / SUPABASE_SERVICE_KEY env vars."""
    global _SUPABASE_URL, _SUPABASE_KEY, _DB_ENABLED
    _SUPABASE_URL = None
    _SUPABASE_KEY = None
    _DB_ENABLED = False


def is_enabled():
    return _DB_ENABLED


def _headers():
    return {
        "apikey": _SUPABASE_KEY,
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation,resolution=merge-duplicates",
    }


def table_exists(table):
    """True if the table exists. Returns False (never raises) for a missing
    relation so the verifier can warn instead of crash before schema.sql has
    been applied. In local-first mode every table exists."""
    if not _DB_ENABLED:
        return True
    try:
        _request("GET", f"{table}?select=id&limit=1")
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        return True
    except Exception:
        return True


def _api(path):
    return f"{_SUPABASE_URL.rstrip('/')}/rest/v1/{path.lstrip('/')}"


def _request(method, path, **kwargs):
    if not _DB_ENABLED:
        return _local_request(method, path, kwargs.get("data"))
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
    if not _DB_ENABLED:
        return _local_upsert(table, data, on_conflict)
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
    if not _DB_ENABLED:
        val = _read_json(_upload_state_path(), {}).get("pending_hashes", [])
        return val if isinstance(val, list) else []
    val = get_setting(f"pending_hashes_{project_id}", [])
    return val if isinstance(val, list) else []


def set_pending_hashes(hashes, project_id="1"):
    if not _DB_ENABLED:
        state = _read_json(_upload_state_path(), {})
        state["pending_hashes"] = hashes if isinstance(hashes, list) else []
        _write_json_atomic(_upload_state_path(), state)
        return
    if not isinstance(hashes, list):
        hashes = []
    set_setting(f"pending_hashes_{project_id}", hashes)


# ─── Settings ────────────────────────────────────────────────────────────

def get_setting(key, default=None):
    if not _DB_ENABLED:
        val = _read_json(_settings_path(), {}).get(key, default)
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return val
        return val
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
    if not _DB_ENABLED:
        vals = _read_json(_settings_path(), {})
        vals[key] = value if isinstance(value, str) else json.dumps(value)
        _write_json_atomic(_settings_path(), vals)
        return
    if not isinstance(value, str):
        value = json.dumps(value)
    _upsert("settings", {"key": key, "value": value, "updated_at": datetime.now(timezone.utc).isoformat()}, on_conflict="key")


def get_all_settings():
    if not _DB_ENABLED:
        return _read_json(_settings_path(), {})
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
    if not _DB_ENABLED:
        for r in get_all_mirror_states(project_id=project_id):
            if r["source_channel"] == source_channel and r["source_video_id"] == source_video_id:
                return r
        return None
    row = _request("GET",
        f"mirror_state?project_id=eq.{project_id}&source_channel=eq.{source_channel}&source_video_id=eq.{source_video_id}&select=*")
    return row[0] if row else None


def get_all_mirror_states(project_id=""):
    if not _DB_ENABLED:
        state = _read_json(_state_path(), {})
        rows = []
        for key, entry in (state.get("processed") or {}).items():
            if ":" in key:
                source, vid = key.split(":", 1)
            else:
                source, vid = key, ""
            rows.append({
                "source_channel": source,
                "source_video_id": vid,
                "mirrored_video_id": entry.get("new_video_id") or entry.get("mirrored_video_id") or "",
                "original_title": entry.get("original_title", ""),
                "mirrored_at": entry.get("mirrored_at") or "",
                "comment_id": entry.get("comment_id", ""),
            })
        return rows
    return _request("GET", f"mirror_state?project_id=eq.{project_id}&select=*") or []


def save_mirror_state(source_channel, source_video_id, data, project_id=""):
    if not _DB_ENABLED:
        state = _read_json(_state_path(), {})
        processed = state.setdefault("processed", {})
        processed[f"{source_channel}:{source_video_id}"] = {
            "new_video_id": data.get("mirrored_video_id") or "",
            "original_title": data.get("original_title", ""),
            "mirrored_at": data.get("mirrored_at") or "",
            "comment_id": data.get("comment_id", ""),
        }
        _write_json_atomic(_state_path(), state)
        return
    data["project_id"] = project_id
    data["source_channel"] = source_channel
    data["source_video_id"] = source_video_id
    data["mirrored_at"] = data.get("mirrored_at") or datetime.now(timezone.utc).isoformat()
    _upsert("mirror_state", data, on_conflict="project_id,source_channel,source_video_id")


# ─── Mirror Stats ────────────────────────────────────────────────────────

def get_mirror_stats(project_id=""):
    if not _DB_ENABLED:
        stats = _read_json(_state_path(), {}).get("stats") or {}
        merged = {"total_mirrored": 0, "total_comments": 0, "total_shortened": 0}
        merged.update(stats)
        return merged
    row = _request("GET", f"mirror_stats?project_id=eq.{project_id}&select=*")
    if row:
        return row[0]
    return {"total_mirrored": 0, "total_comments": 0, "total_shortened": 0}


def update_mirror_stats(stats, project_id=""):
    if not _DB_ENABLED:
        state = _read_json(_state_path(), {})
        merged = {"total_mirrored": 0, "total_comments": 0, "total_shortened": 0}
        merged.update(stats or {})
        state["stats"] = merged
        _write_json_atomic(_state_path(), state)
        return
    stats["project_id"] = project_id
    stats["updated_at"] = datetime.now(timezone.utc).isoformat()
    _upsert("mirror_stats", stats, on_conflict="project_id")


# ─── Upload State ────────────────────────────────────────────────────────

def get_upload_state(project_id=""):
    if not _DB_ENABLED:
        state = _read_json(_upload_state_path(), {})
        defaults = {
            "project_id": project_id,
            "account_created": None, "warmup_start": None,
            "warmup_complete": False, "first_upload_date": None,
            "total_uploaded": 0, "last_upload_date": None,
            "last_upload_hour": None, "processed_hashes": [],
            "pending_hashes": [],
            "filled_slots": [],
            "filled_slots_date": "",
            "yt_client_id": "",
        }
        defaults.update(state)
        return defaults
    row = _request("GET", f"upload_state?project_id=eq.{project_id}&select=*")
    if row:
        s = row[0]
        if isinstance(s.get("processed_hashes"), list):
            s["processed_hashes"] = [h for h in s["processed_hashes"]]
        if isinstance(s.get("filled_slots"), list):
            s["filled_slots"] = [x for x in s["filled_slots"]]
        return s
    return {
        "project_id": project_id,
        "account_created": None, "warmup_start": None,
        "warmup_complete": False, "first_upload_date": None,
        "total_uploaded": 0, "last_upload_date": None,
        "last_upload_hour": None, "processed_hashes": [],
        "filled_slots": [],
        "filled_slots_date": "",
        "yt_client_id": "",
    }


def save_upload_state(state, project_id=""):
    if not _DB_ENABLED:
        existing = _read_json(_upload_state_path(), {})
        existing.update({k: v for k, v in state.items() if k != "project_id"})
        _write_json_atomic(_upload_state_path(), existing)
        return
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
        "filled_slots": state.get("filled_slots", []),
        "filled_slots_date": state.get("filled_slots_date") or None,
        "yt_client_id": state.get("yt_client_id", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _upsert("upload_state", row, on_conflict="project_id")


# ─── Upload Logs ─────────────────────────────────────────────────────────

def get_upload_logs(limit=100, project_id=""):
    if not _DB_ENABLED:
        log = _read_json(_daily_log_path(), {"uploads": []})
        uploads = [dict(u) for u in log.get("uploads", [])]
        uploads.reverse()
        return uploads[:limit]
    return _request("GET", f"upload_logs?select=*&project_id=eq.{project_id}&order=upload_time.desc&limit={limit}") or []


def get_today_upload_count(date_str, project_id=""):
    if not _DB_ENABLED:
        log = _read_json(_daily_log_path(), {"uploads": []})
        return sum(1 for u in log.get("uploads", [])
                   if (u.get("upload_date") or "").startswith(date_str))
    rows = _request("GET",
        f"upload_logs?select=id&project_id=eq.{project_id}&upload_date=eq.{date_str}")
    return len(rows) if rows else 0


def add_upload_log(entry, project_id=""):
    if not _DB_ENABLED:
        log = _read_json(_daily_log_path(), {"uploads": []})
        uploads = log.get("uploads", [])
        uploads.append(entry)
        if len(uploads) > 100:
            uploads = uploads[-100:]
        _write_json_atomic(_daily_log_path(), {"uploads": uploads})
        return
    entry["project_id"] = project_id
    try:
        _request("POST", "upload_logs", data=entry)
    except urllib.error.HTTPError as e:
        if e.code == 400 and ("source_video_id" in str(e) or "source_channel" in str(e)):
            # schema.sql not applied yet (columns missing) — log without them
            entry.pop("source_video_id", None)
            entry.pop("source_channel", None)
            _request("POST", "upload_logs", data=entry)
        else:
            raise


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


# ─── Work Queue / Checklist ─────────────────────────────────────────────

def add_work_item(work_type, project_id="", **fields):
    data = {
        "project_id": project_id,
        "work_type": work_type,
        "status": fields.get("status", "pending"),
        "video_id": fields.get("video_id", ""),
        "source_url": fields.get("source_url", ""),
        "title": fields.get("title", ""),
        "slot_time": fields.get("slot_time", ""),
        "error": fields.get("error", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = _request("POST", "work_queue", data=data)
    if isinstance(result, list) and len(result) > 0:
        return result[0]
    return result


def update_work_item(item_id, **fields):
    data = {"updated_at": datetime.now(timezone.utc).isoformat()}
    for k in ("status", "error"):
        if k in fields:
            data[k] = fields[k]
    _request("PATCH", f"work_queue?id=eq.{item_id}", data=data)


def get_work_queue(project_id="", limit=50, status=None):
    filters = [f"project_id=eq.{project_id}"]
    if status:
        filters.append(f"status=eq.{status}")
    query = "&".join(filters) + f"&order=created_at.desc&limit={limit}"
    return _request("GET", f"work_queue?select=id,work_type,status,video_id,title,slot_time,error,created_at,updated_at&{query}") or []


def get_work_stats(project_id=""):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = _request("GET",
        f"work_queue?select=status&project_id=eq.{project_id}&created_at=gte.{today}T00:00:00Z")
    if rows is None:
        return {"total": 0, "done": 0, "failed": 0, "pending": 0}
    total = len(rows)
    done = sum(1 for r in rows if r.get("status") == "done")
    failed = sum(1 for r in rows if r.get("status") == "failed")
    pending = total - done - failed
    return {"total": total, "done": done, "failed": failed, "pending": pending}


# ─── Run Locks (parallel-run guard) ─────────────────────────────────────

def _parse_ts(v):
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t
    except Exception:
        return None


HEARTBEAT_STALE_MINUTES = 90
LOCK_STEAL_GRACE_MIN = 15  # owner needs time to write its first heartbeat


def _lock_owner_alive(project_id="", lock_owner=""):
    """A run can only prove it is alive by heartbeating. No fresh heartbeat
    from the lock owner means it crashed/hung (cancel skips the finally
    block, so the lock would otherwise block new runs for the full TTL)."""
    try:
        hb = _request("GET", f"run_heartbeats?project_id=eq.{project_id}&select=run_id,last_seen")
    except Exception:
        # heartbeat table missing (schema not applied) — be conservative and
        # treat the owner as alive rather than stealing the lock or crashing
        return True
    if not hb:
        return False
    row = hb[0]
    if row.get("run_id") != lock_owner:
        return False
    t = _parse_ts(row.get("last_seen"))
    if not t:
        return False
    return (datetime.now(timezone.utc) - t).total_seconds() < HEARTBEAT_STALE_MINUTES * 60


def acquire_run_lock(project_id="", owner="", ttl_hours=6):
    now = datetime.now(timezone.utc)
    rows = _request("GET", f"run_locks?project_id=eq.{project_id}&select=*")
    if rows:
        lock = rows[0]
        acquired = lock.get("acquired_at")
        owner_now = lock.get("owner", "")
        if acquired:
            t = _parse_ts(acquired)
            expired = (t is None) or ((now - t).total_seconds() >= ttl_hours * 3600)
        else:
            expired = True
        if owner_now and not expired and owner_now != owner and _lock_owner_alive(project_id, owner_now):
            return False, owner_now
        acquired_t = _parse_ts(acquired) if owner_now and not expired and owner_now != owner else None
        if acquired_t and (now - acquired_t).total_seconds() >= LOCK_STEAL_GRACE_MIN * 60:
            # Lock owner stopped heartbeating (crashed/hung — its finally
            # block never ran) so it is safe to steal the lock.
            try:
                update_heartbeat(project_id=project_id, run_id=owner_now,
                                 status="crashed", message="lock stolen — owner heartbeat went stale")
            except Exception:
                pass
        _request("PATCH", f"run_locks?project_id=eq.{project_id}", data={
            "owner": owner,
            "acquired_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=ttl_hours)).isoformat(),
            "updated_at": now.isoformat(),
        })
        return True, owner
    _request("POST", "run_locks", data={
        "project_id": project_id,
        "owner": owner,
        "acquired_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=ttl_hours)).isoformat(),
        "updated_at": now.isoformat(),
    })
    return True, owner


def release_run_lock(project_id="", owner=""):
    rows = _request("GET", f"run_locks?project_id=eq.{project_id}&select=owner")
    if rows and (not owner or rows[0].get("owner") == owner):
        _request("DELETE", f"run_locks?project_id=eq.{project_id}")


def clear_expired_locks():
    """Delete run locks whose TTL has passed (a crashed run can never release
    its own lock, so this prevents them from lingering past their TTL)."""
    rows = _request("GET", "run_locks?select=project_id,expires_at")
    removed = 0
    for r in rows or []:
        t = _parse_ts(r.get("expires_at"))
        if t and t < datetime.now(timezone.utc):
            _request("DELETE", f"run_locks?project_id=eq.{r['project_id']}")
            removed += 1
    return removed


# ─── Heartbeats (liveness proof — see run_locks) ──────────────────────────

def update_heartbeat(project_id="", run_id="", iteration=0, status="running", message=""):
    now = datetime.now(timezone.utc).isoformat()
    _upsert("run_heartbeats", {
        "project_id": project_id,
        "run_id": run_id,
        "iteration": iteration,
        "status": status,
        "message": message,
        "last_seen": now,
        "updated_at": now,
    }, on_conflict="project_id")


def get_heartbeat(project_id=""):
    row = _request("GET", f"run_heartbeats?project_id=eq.{project_id}&select=*")
    return row[0] if row else None


# ─── Work queue hygiene ────────────────────────────────────────────────────

def close_stale_work_items(project_id="", stale_minutes=45):
    """Mark in_progress work items that have not been touched for a long time
    as failed, so they never sit 'in_progress' forever (which would break
    queue accounting and block re-dispatch of that video)."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    rows = _request("GET",
        f"work_queue?project_id=eq.{project_id}&status=eq.in_progress"
        f"&select=id,updated_at&order=updated_at.asc&limit=100")
    closed = 0
    for r in rows or []:
        t = _parse_ts(r.get("updated_at"))
        if t and t < cutoff:
            update_work_item(r["id"], status="failed", error="stale — in_progress too long")
            closed += 1
    return closed


# ─── Verify checks (self-verification audit trail) ────────────────────────

def record_verify_check(project_id="", check_name="", status="ok", message="", details=None):
    now = datetime.now(timezone.utc).isoformat()
    _upsert("verify_checks", {
        "project_id": project_id,
        "check_name": check_name,
        "status": status,
        "message": message,
        "details": details or {},
        "checked_at": now,
    }, on_conflict="project_id,check_name")


# ─── Alerts (recurring issues surfaced until fixed) ───────────────────────

def add_alert(project_id="", severity="warn", check_name="", message="", details=None):
    _request("POST", "alerts", data={
        "project_id": project_id,
        "severity": severity,
        "check_name": check_name,
        "message": message,
        "details": details or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def get_open_alerts(project_id="", limit=50):
    return _request("GET",
        f"alerts?project_id=eq.{project_id}&resolved_at=is.null"
        f"&select=*&order=created_at.desc&limit={limit}") or []


def resolve_alert(alert_id, by="bot"):
    now = datetime.now(timezone.utc).isoformat()
    _request("PATCH", f"alerts?id=eq.{alert_id}", data={"resolved_at": now, "resolved_by": by})


# ─── Local JSON backend (local-first mode) ────────────────────────────────
# When SUPABASE_URL / SUPABASE_SERVICE_KEY are absent, every table persists to
# local JSON files under ~/.yt-mirror/ so the bot runs fully standalone.
# Tables with an established local file (upload_state.json, daily_log.json,
# state.json, settings.json) map onto those formats so config.py /
# daily_uploader.py readers stay consistent; the rest use canonical files.

_DATA_DIR = Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror")))
_STORE_DIR = _DATA_DIR / "store"


def _store_dir():
    return Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror"))) / "store"


def _upload_state_path():
    return Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror"))) / "upload_state.json"


def _daily_log_path():
    return Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror"))) / "daily_log.json"


def _state_path():
    return Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror"))) / "state.json"


def _settings_path():
    return Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror"))) / "settings.json"


_STORE_FILES = {
    "projects": "projects.json",
    "channel_cursors": "cursors.json",
    "work_queue": "work_queue.json",
    "run_locks": "run_locks.json",
    "run_heartbeats": "run_heartbeats.json",
    "alerts": "alerts.json",
    "verify_checks": "verify_checks.json",
    "channels": "channels_table.json",
    "accounts": "accounts_table.json",
    "settings": "settings_table.json",
    "upload_state": "upload_state_table.json",
    "upload_logs": "upload_logs_table.json",
}

_ID_TABLES = {"work_queue", "alerts", "projects"}


def _read_json(path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default


def _write_json_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp")
    try:
        os.write(fd, json.dumps(value, indent=2).encode("utf-8"))
        os.close(fd)
        os.chmod(tmp, 0o600)
        os.rename(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _store_file(table):
    return _store_dir() / _STORE_FILES.get(table, table + ".json")


def _load_rows(table):
    return _read_json(_store_file(table), [])


def _save_rows(table, rows):
    _write_json_atomic(_store_file(table), rows)


def _next_id(rows):
    ids = [r.get("id") for r in rows if isinstance(r.get("id"), int)]
    return (max(ids) + 1) if ids else 1


def _parse_value(raw):
    if raw in (None, "null"):
        return None
    if raw in ("true", "True"):
        return True
    if raw in ("false", "False"):
        return False
    try:
        return int(raw)
    except (ValueError, TypeError):
        try:
            return float(raw)
        except (ValueError, TypeError):
            return raw


def _row_matches(row, filters):
    for key, op, val in filters:
        rv = row.get(key)
        if op == "is":
            if val == "null":
                if rv is not None and rv != "":
                    return False
            elif val in ("true", "false"):
                if bool(rv) != (val == "true"):
                    return False
            continue
        if op == "in":
            items = [i.strip() for i in val.strip("()").split(",") if i.strip()]
            if rv not in [_parse_value(i) for i in items]:
                return False
            continue
        if op == "like":
            import fnmatch
            if not fnmatch.fnmatchcase(str(rv), str(val)):
                return False
            continue
        pv = _parse_value(val)
        if op == "eq":
            if rv != pv:
                return False
        elif op == "neq":
            if rv == pv:
                return False
        elif op in ("gt", "gte", "lt", "lte"):
            try:
                ok = {"gt": rv > pv, "gte": rv >= pv, "lt": rv < pv, "lte": rv <= pv}[op]
            except TypeError:
                rvs, pvs = str(rv), str(pv)
                ok = {"gt": rvs > pvs, "gte": rvs >= pvs, "lt": rvs < pvs, "lte": rvs <= pvs}[op]
            if not ok:
                return False
        else:
            return False
    return True


def _sort_key(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return v
    return str(v)


def _parse_query(qs):
    parsed = {"select": [], "filters": [], "order": [], "limit": None}
    if not qs:
        return parsed
    params = urllib.parse.parse_qs(qs, keep_blank_values=True)
    for v in params.get("select", []):
        for part in v.split(","):
            part = part.strip()
            if part and part not in parsed["select"]:
                parsed["select"].append(part)
    for key, vals in params.items():
        if key in ("select", "order", "limit"):
            continue
        for v in vals:
            op, raw = "eq", v
            if "." in v:
                maybe_op, _, maybe_val = v.partition(".")
                if maybe_op in ("eq", "neq", "gt", "gte", "lt", "lte", "is", "like", "ilike", "in"):
                    op, raw = maybe_op, maybe_val
            parsed["filters"].append((key, op, raw))
    for v in params.get("order", []):
        for part in v.split(","):
            part = part.strip()
            if not part:
                continue
            col, _, direction = part.partition(".")
            parsed["order"].append((col, "asc" if direction != "desc" else "desc"))
    if params.get("limit"):
        try:
            parsed["limit"] = int(params["limit"][0])
        except (ValueError, TypeError):
            parsed["limit"] = None
    return parsed


def _project(row, select_cols):
    if not select_cols:
        return dict(row)
    out = {}
    for c in select_cols:
        if c == "*":
            return dict(row)
        out[c] = row.get(c)
    return out


def _local_request(method, path, data=None):
    table = path.split("?")[0].split("/")[-1]
    q = _parse_query(path.partition("?")[2])
    rows = _load_rows(table)

    if method == "GET":
        out = [r for r in rows if _row_matches(r, q["filters"])]
        out = [_project(r, q["select"]) for r in out]
        for col, direction in q["order"]:
            out.sort(key=lambda r, c=col: _sort_key(r.get(c)), reverse=(direction == "desc"))
        if q["limit"] is not None:
            out = out[:q["limit"]]
        return out

    if method == "POST":
        row = dict(data or {})
        if "id" not in row and table in _ID_TABLES:
            row["id"] = _next_id(rows)
        rows.append(row)
        _save_rows(table, rows)
        return [row]

    if method == "PATCH":
        changed = []
        for r in rows:
            if _row_matches(r, q["filters"]):
                r.update(data or {})
                changed.append(r)
        _save_rows(table, rows)
        return changed

    if method == "DELETE":
        keep = [r for r in rows if not _row_matches(r, q["filters"])]
        _save_rows(table, keep)
        return []

    return []


def _local_upsert(table, data, on_conflict="id"):
    keys = [k.strip() for k in on_conflict.split(",")]
    rows = _load_rows(table)
    for r in rows:
        if all(r.get(k) == data.get(k) for k in keys):
            r.update(data or {})
            _save_rows(table, rows)
            return [r]
    row = dict(data or {})
    if "id" not in row and table in _ID_TABLES:
        row["id"] = _next_id(rows)
    rows.append(row)
    _save_rows(table, rows)
    return [row]


# ─── Init ────────────────────────────────────────────────────────────────

configure()
