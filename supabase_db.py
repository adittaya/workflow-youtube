import os
import json
import time
import urllib.error
from datetime import datetime, timezone, timedelta

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


def table_exists(table):
    """True if the table exists. Returns False (never raises) for a missing
    relation so the verifier can warn instead of crash before schema.sql has
    been applied."""
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
    return _request("GET", f"upload_logs?select=*&project_id=eq.{project_id}&order=upload_time.desc&limit={limit}") or []


def get_today_upload_count(date_str, project_id=""):
    rows = _request("GET",
        f"upload_logs?select=id&project_id=eq.{project_id}&upload_date=eq.{date_str}")
    return len(rows) if rows else 0


def add_upload_log(entry, project_id=""):
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
    hb = _request("GET", f"run_heartbeats?project_id=eq.{project_id}&select=run_id,last_seen")
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


# ─── Init ────────────────────────────────────────────────────────────────

configure()
