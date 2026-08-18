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


def _enc(value):
    """URL-encode a filter value so names with spaces/special chars (e.g.
    an account called 'My Main Channel') never break the REST query."""
    return urllib.parse.quote(str(value), safe="")


def _request(method, path, **kwargs):
    if not _DB_ENABLED:
        return _local_request(method, path, kwargs.get("data"))
    import urllib.request
    import urllib.error
    url = _api(path)
    # Safety net: even if a future call site forgets _enc(), a raw space or
    # other whitespace must never reach urlopen (http.client would raise
    # InvalidURL). Encode whitespace in place; everything else is untouched.
    if any(ch.isspace() for ch in url):
        url = "".join(urllib.parse.quote(ch) if ch.isspace() else ch for ch in url)
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
            key_filter = "&".join(f"{k}=eq.{_enc(data.get(k))}" for k in key_cols if data.get(k) is not None)
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

def _decode_setting(val, default):
    """Decode a stored setting value. Values are stored natively (JSON), so a
    string "3128" must come back as "3128". Two legacy encodings are healed:
    objects/arrays stored as json.dumps'd strings, and strings that were
    double-encoded (json.dumps'd once more, e.g. a URL stored as
    '"https://…"' — breaking urlsplit's scheme parsing)."""
    if isinstance(val, str):
        if val[:1] in ("{", "[") or (len(val) >= 2 and val[0] == '"' and val[-1] == '"'):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return val
    return val


def get_setting(key, default=None):
    """Settings round-trip: values are stored natively (JSON), so a string
    "3128" must come back as "3128", never as int 3128. Legacy rows written
    as json.dumps'd strings (objects/arrays/quoted strings) are decoded."""
    if not _DB_ENABLED:
        return _decode_setting(_read_json(_settings_path(), {}).get(key, default), default)
    row = _request("GET", f"settings?key=eq.{_enc(key)}&select=value")
    if row:
        return _decode_setting(row[0]["value"], default)
    return default


def set_setting(key, value):
    if not _DB_ENABLED:
        vals = _read_json(_settings_path(), {})
        vals[key] = value
        _write_json_atomic(_settings_path(), vals)
        return
    # Send native JSON values so a bool stays a bool (jsonb): an old json.dumps
    # path stored 'true' as a JSON *string*, which read back as the string
    # "true" — a falsey flag like 'false' then became truthy for naive callers.
    _upsert("settings", {"key": key, "value": value, "updated_at": datetime.now(timezone.utc).isoformat()}, on_conflict="key")


# ─── Accounts ────────────────────────────────────────────────────────────

def _local_accounts_rows():
    """Local-mode accounts live in accounts.json via config (single store).
    Rows are plain dicts keyed by name with the full field set preserved."""
    import config as _config
    rows = []
    for name, data in (_config.load_accounts() or {}).items():
        row = dict(data)
        row["name"] = name
        rows.append(row)
    return rows


def _save_local_accounts_rows(rows):
    import config as _config
    accts = {}
    for r in rows:
        data = dict(r)
        name = data.pop("name", "")
        if name:
            accts[name] = data
    _config.save_accounts(accts)


def get_account(name):
    if not _DB_ENABLED:
        return next((r for r in _local_accounts_rows() if r.get("name") == name), None)
    row = _request("GET", f"accounts?name=eq.{_enc(name)}&select=*")
    return row[0] if row else None


def get_all_accounts():
    if not _DB_ENABLED:
        return _local_accounts_rows()
    return _request("GET", "accounts?select=*") or []


def save_account(name, data):
    data["name"] = name
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    if not _DB_ENABLED:
        rows = _local_accounts_rows()
        for r in rows:
            if r.get("name") == name:
                r.update(data)
                _save_local_accounts_rows(rows)
                return
        rows.append(dict(data))
        _save_local_accounts_rows(rows)
        return
    # Postgres checks NOT NULL before ON CONFLICT resolution, so a partial
    # payload (e.g. verify_account writing only status) can never merge via
    # the API alone. Merge with the existing row first, like local mode.
    existing = get_account(name)
    if existing:
        merged = dict(existing)
        merged.update(data)
        data = merged
    _upsert("accounts", data, on_conflict="name")


def delete_account(name):
    if not _DB_ENABLED:
        _save_local_accounts_rows([r for r in _local_accounts_rows() if r.get("name") != name])
        return
    _request("DELETE", f"accounts?name=eq.{_enc(name)}")


def set_project_account(project_id, account_name):
    """Link a project to the account that uploads on its behalf."""
    update_project(project_id, account_id=account_name or "")


def get_project_account(project_id):
    """Resolve the account linked to a project, or None."""
    project = get_project(project_id)
    if not project or not project.get("account_id"):
        return None
    return get_account(project["account_id"])


def verify_account(name, status="active", last_error="", expires_in=7 * 24 * 3600):
    """Record the result of a live OAuth token test on an account.

    status: 'active' (token refresh OK) or 'expired' (token rejected).
    expires_in: seconds the refresh token is expected to stay valid from now
    (Google rotates refresh tokens to ~7 days after they are issued)."""
    account = get_account(name)
    if not account:
        return
    now = datetime.now(timezone.utc)
    data = {
        "status": status,
        "last_verified": now.isoformat(),
        "last_error": last_error or "",
    }
    if status == "active":
        data["token_expires_at"] = (now + timedelta(seconds=expires_in)).isoformat()
        data["last_error"] = ""
    else:
        data["token_expires_at"] = None
    save_account(name, data)


def increment_account_uploads(name):
    account = get_account(name)
    if not account:
        return
    save_account(name, {"uploads_count": int(account.get("uploads_count", 0) or 0) + 1})


# ─── Upload State ────────────────────────────────────────────────────────

def get_upload_state(project_id=""):
    if not _DB_ENABLED:
        state = _read_json(_upload_state_path(), {})
        defaults = {
            "project_id": project_id,
            "account_created": None, "first_upload_date": None,
            "total_uploaded": 0, "last_upload_date": None,
            "last_upload_hour": None, "processed_hashes": [],
            "pending_hashes": [],
            "yt_client_id": "",
        }
        defaults.update(state)
        return defaults
    row = _request("GET", f"upload_state?project_id=eq.{_enc(project_id)}&select=*")
    if row:
        s = row[0]
        if isinstance(s.get("processed_hashes"), list):
            s["processed_hashes"] = [h for h in s["processed_hashes"]]
        return s
    return {
        "project_id": project_id,
        "account_created": None, "first_upload_date": None,
        "total_uploaded": 0, "last_upload_date": None,
        "last_upload_hour": None, "processed_hashes": [],
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
        "first_upload_date": state.get("first_upload_date"),
        "total_uploaded": state.get("total_uploaded", 0),
        "last_upload_date": state.get("last_upload_date"),
        "last_upload_hour": state.get("last_upload_hour"),
        "processed_hashes": state.get("processed_hashes", []),
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
    return _request("GET", f"upload_logs?select=*&project_id=eq.{_enc(project_id)}&order=upload_time.desc&limit={limit}") or []


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
        if e.code == 400 and ("source_video_id" in str(e) or "source_channel" in str(e)
                              or "account_name" in str(e)):
            # schema.sql not applied yet (columns missing) — log without them
            entry.pop("source_video_id", None)
            entry.pop("source_channel", None)
            entry.pop("account_name", None)
            _request("POST", "upload_logs", data=entry)
        else:
            raise


# ─── Projects ───────────────────────────────────────────────────────────────

def list_projects():
    rows = _request("GET", "projects?select=*&order=name.asc")
    return rows or []


def get_project(project_id):
    row = _request("GET", f"projects?id=eq.{_enc(project_id)}&select=*")
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
    """Update arbitrary project fields. Values passed explicitly are applied
    even when None (clearing a field), unlike create_project which drops None."""
    data = {"updated_at": datetime.now(timezone.utc).isoformat()}
    for k, v in fields.items():
        data[k] = v
    _request("PATCH", f"projects?id=eq.{_enc(project_id)}", data=data)
    return get_project(project_id)


def delete_project(project_id):
    _request("DELETE", f"projects?id=eq.{_enc(project_id)}")


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

def get_open_alerts(project_id="", limit=50):
    return _request("GET",
        f"alerts?project_id=eq.{_enc(project_id)}&resolved_at=is.null"
        f"&select=*&order=created_at.desc&limit={limit}") or []


def resolve_alert(alert_id, by="bot"):
    now = datetime.now(timezone.utc).isoformat()
    _request("PATCH", f"alerts?id=eq.{_enc(alert_id)}", data={"resolved_at": now, "resolved_by": by})


# ─── Local JSON backend (local-first mode) ────────────────────────────────
# When SUPABASE_URL / SUPABASE_SERVICE_KEY are absent, every table persists to
# local JSON files under ~/.yt-mirror/ so the tool runs fully standalone.
# Tables with an established local file (upload_state.json, daily_log.json,
# settings.json) map onto those formats so config.py / daily_uploader.py
# readers stay consistent; the rest use canonical files.


def _store_dir():
    return Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror"))) / "store"


def _upload_state_path():
    return Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror"))) / "upload_state.json"


def _daily_log_path():
    return Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror"))) / "daily_log.json"


def _settings_path():
    return Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror"))) / "settings.json"


_STORE_FILES = {
    "projects": "projects.json",
    "alerts": "alerts.json",
    "verify_checks": "verify_checks.json",
    "accounts": "accounts_table.json",
    "settings": "settings_table.json",
    "upload_state": "upload_state_table.json",
    "upload_logs": "upload_logs_table.json",
}

_ID_TABLES = {"alerts", "projects"}


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
