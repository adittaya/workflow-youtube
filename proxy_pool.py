#!/usr/bin/env python3
"""proxy_pool.py — automated proxy pool manager.

Reads the proxy inventory from a dedicated Supabase project (the "proxy
database"), live-tests every proxy, writes the results back (latency_ms,
e2_ok, vplink_ok, verified, last_seen), picks the fastest working one and
activates it in the shared proxy settings — then watches it and auto-repools
("refreshes the dead proxies and picks a fast one") whenever the active proxy
stops working.

Pool database tables (proxy project schema):
    proxy_results  — inventory: ip, port, proto, latency_ms, e2_ok, vplink_ok,
                     verified, first_seen, last_seen, ...
    proxy_state    — rotation bookkeeping: ip, port, state='used', expires_at

Credentials come from the settings store (proxy_pool_url / proxy_pool_key) or
the PROXY_POOL_URL / PROXY_POOL_KEY environment variables.
"""

import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import config

TEST_E2_URL = "https://oauth2.googleapis.com/token"
TEST_VPLINK_URL = "https://vplink.in/api"
TCP_TIMEOUT = 4
HTTP_TIMEOUT = 7
REFRESH_CONCURRENCY = 20
STALE_AFTER_MIN = 5
USED_TTL_HOURS = 24


# ─── Pool credentials ────────────────────────────────────────────────────────

def get_pool_url():
    return (os.environ.get("PROXY_POOL_URL", "")
            or str(config.get_proxy_settings().get("proxy_pool_url", "") or "").strip())


def get_pool_key():
    return (os.environ.get("PROXY_POOL_KEY", "")
            or str(config.get_proxy_settings().get("proxy_pool_key", "") or "").strip())


def is_configured():
    return bool(get_pool_url() and get_pool_key())


def is_enabled():
    return _truthy(config.get_proxy_settings().get("proxy_pool_enabled"))


def _truthy(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# ─── Pool REST (small, proxy-DB-specific client) ────────────────────────────

def _request(method, path, data=None):
    base = get_pool_url().rstrip("/")
    key = get_pool_key()
    url = f"{base}/rest/v1/{path.lstrip('/')}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation,resolution=merge-duplicates",
        },
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else None


def list_pool():
    """Return the proxy inventory rows (proxy_results), latency ascending."""
    return _request("GET", "proxy_results?select=*&limit=1000&order=latency_ms.asc") or []


def _used_unexpired():
    """Set of (ip, port) currently marked 'used' with a future expiry."""
    try:
        rows = _request("GET", "proxy_state?state=eq.used&select=ip,port,expires_at") or []
    except Exception:
        return set()
    now = datetime.now(timezone.utc)
    out = set()
    for r in rows:
        exp = r.get("expires_at")
        try:
            t = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if t > now:
                out.add((str(r.get("ip", "")), int(r.get("port") or 0)))
        except Exception:
            continue
    return out


def _mark_used(ip, port):
    """Record a proxy as 'used' for rotation (expires after USED_TTL_HOURS)."""
    now = datetime.now(timezone.utc)
    data = {
        "ip": str(ip),
        "port": int(port),
        "state": "used",
        "expires_at": (now + timedelta(hours=USED_TTL_HOURS)).isoformat(),
        "created_at": now.isoformat(),
    }
    q = urllib.parse.quote_plus(f"ip=eq.{ip}") + "&" + urllib.parse.quote_plus(f"port=eq.{int(port)}")
    try:
        existing = _request("GET", f"proxy_state?{q}&select=ip,port") or []
        if existing:
            _request("PATCH", f"proxy_state?{q}", data)
        else:
            _request("POST", "proxy_state", data)
    except Exception:
        pass


# ─── Live testing ────────────────────────────────────────────────────────────

def _tcp_reachable(ip, port):
    try:
        with socket.create_connection((ip, int(port)), timeout=TCP_TIMEOUT):
            return True
    except OSError:
        return False


def _probe(proxy_url, target, timeout):
    """Return (latency_ms, http_status) for a request through the proxy, or
    (None, None) on any failure."""
    try:
        import httplib2
        http = httplib2.Http(
            timeout=timeout,
            proxy_info=httplib2.proxy_info_from_url(proxy_url, "https"),
        )
        start = time.time()
        resp, _body = http.request(target, method="GET")
        return int((time.time() - start) * 1000), resp.status
    except Exception:
        return None, None


def test_one(ip, port, proto="http", timeout=HTTP_TIMEOUT):
    """Test a single proxy. Returns (ok, latency_ms, vplink_ok, note)."""
    ip = str(ip)
    port = int(port)
    proto = str(proto or "http")
    if not _tcp_reachable(ip, port):
        return False, None, False, "unreachable (TCP refused)"
    url = f"{proto}://{ip}:{port}"
    lat, status = _probe(url, TEST_E2_URL, timeout)
    if lat is None:
        return False, None, False, "no HTTP response"
    vlat, vstatus = _probe(url, TEST_VPLINK_URL, timeout)
    return True, lat, (vlat is not None and vstatus < 500), f"HTTP {status}"


def refresh_pool(progress=None):
    """Test every proxy in the pool, write results back to the DB and return
    the updated rows. `progress(done, total, ip)` is called as testing runs."""
    rows = list_pool()
    total = len(rows)
    if not total:
        return []
    updated = []
    done = 0

    def work(row):
        ok, lat, vpl, note = test_one(row.get("ip"), row.get("port"), row.get("proto", "http"))
        row = dict(row)
        row["e2_ok"] = ok
        row["vplink_ok"] = bool(vpl)
        row["latency_ms"] = lat
        row["note"] = note
        if ok:
            row["verified"] = int(row.get("verified", 0) or 0) + 1
        row["last_seen"] = datetime.now(timezone.utc).isoformat()
        return row

    with ThreadPoolExecutor(max_workers=REFRESH_CONCURRENCY) as ex:
        for row in ex.map(work, rows):
            updated.append(row)
            done += 1
            if progress:
                progress(done, total, row.get("ip", ""))

    # Persist results (PATCH each row by its uuid id)
    now = datetime.now(timezone.utc).isoformat()
    for row in updated:
        try:
            _request("PATCH", f"proxy_results?id=eq.{row['id']}", {
                "latency_ms": row.get("latency_ms"),
                "e2_ok": row.get("e2_ok", False),
                "vplink_ok": row.get("vplink_ok", False),
                "verified": row.get("verified", 1),
                "last_seen": now,
            })
        except Exception:
            pass
    return updated


def pick_best(rows):
    """Fastest working proxy; prefers proxies not currently marked 'used' and
    ignores rows whose latency is 0/missing (untested, not 'fast')."""
    alive = [r for r in rows if r.get("e2_ok") and r.get("ip")]
    if not alive:
        return None
    used = _used_unexpired()

    def tested(r):
        return isinstance(r.get("latency_ms"), int) and r["latency_ms"] > 0

    def key(r):
        return r["latency_ms"] if tested(r) else 10 ** 9

    candidates = [r for r in alive if (str(r["ip"]), int(r.get("port") or 0)) not in used]
    candidates = candidates or alive
    tested_rows = [r for r in candidates if tested(r)]
    candidates = tested_rows or candidates
    return sorted(candidates, key=key)[0]


def candidate_urls(limit=None):
    """Ordered working pool proxy URLs (fastest first, skipping proxies already
    marked used) so the download path can rotate through proxies when one is
    blocked by YouTube. Returns [] when the pool is disabled, not configured,
    or has no working proxies. `limit` caps how many URLs to return; None (the
    default) returns every working proxy — no rotation cap."""
    if limit is None:
        limit = 10 ** 9
    if not is_enabled() or not is_configured():
        return []
    try:
        rows = list_pool()
    except Exception:
        return []
    alive = [r for r in rows if r.get("e2_ok") and r.get("ip")]
    if not alive:
        return []
    used = _used_unexpired()
    candidates = [r for r in alive if (str(r["ip"]), int(r.get("port") or 0)) not in used]
    candidates = candidates or alive

    def tested(r):
        return isinstance(r.get("latency_ms"), int) and r["latency_ms"] > 0

    def key(r):
        return r["latency_ms"] if tested(r) else 10 ** 9

    ordered = sorted(candidates, key=key)
    urls = []
    for r in ordered:
        url = f"{str(r.get('proto') or 'http')}://{r['ip']}:{r.get('port')}"
        if url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def mark_blocked(url):
    """Park a proxy that failed (e.g. YouTube bot-check) so future rotation
    skips it. The IP:port is marked 'used' for USED_TTL_HOURS."""
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(str(url))
        if parts.hostname:
            _mark_used(parts.hostname, parts.port or 0)
    except Exception:
        pass


# ─── Activation / failover ───────────────────────────────────────────────────

def activate(proxy):
    """Write the chosen proxy into the shared proxy settings so every network
    op (uploads, downloads, OAuth, shortener) uses it."""
    ip = str(proxy["ip"])
    port = int(proxy.get("port") or 0)
    proto = str(proxy.get("proto") or "http")
    lat = proxy.get("latency_ms")
    config.save_proxy_settings(
        proxy_enabled=True,
        proxy_protocol=proto,
        proxy_host=ip,
        proxy_port=str(port),
        proxy_username="",
        proxy_password="",
        proxy_active_ip=ip,
        proxy_active_port=str(port),
        proxy_active_proto=proto,
        proxy_active_latency=lat if isinstance(lat, int) else 0,
        proxy_picked_at=datetime.now(timezone.utc).isoformat(),
    )
    _mark_used(ip, port)
    return proxy


def active_proxy():
    """Describe the currently active pooled proxy, or None."""
    s = config.get_proxy_settings()
    ip = str(s.get("proxy_active_ip", "") or "").strip()
    if not ip:
        return None
    return {
        "ip": ip,
        "port": str(s.get("proxy_active_port", "") or "").strip(),
        "proto": str(s.get("proxy_active_proto", "") or "http"),
        "latency_ms": s.get("proxy_active_latency", 0),
        "picked_at": s.get("proxy_picked_at", ""),
    }


def refresh_and_activate(progress=None):
    """Full cycle: refresh the pool, then pick & activate the fastest live
    proxy. Returns (proxy_or_None, message)."""
    if not is_configured():
        return None, "proxy pool not configured (set URL and key in Settings)"
    try:
        rows = refresh_pool(progress=progress)
    except Exception as e:
        return None, f"pool refresh failed: {str(e)[:80]}"
    if not rows:
        return None, "pool is empty — nothing to test"
    alive = [r for r in rows if r.get("e2_ok")]
    if not alive:
        return None, "0 proxies working after refresh — try again later or use manual proxy"
    best = pick_best(rows)
    activate(best)
    lat = best.get("latency_ms")
    return best, (f"activated {best['ip']}:{best.get('port')} "
                  f"({lat}ms) — {len(alive)}/{len(rows)} proxies alive")


def ensure_working(force=False):
    """Before any network op: make sure a working pooled proxy is active.
    Re-tests the active proxy and repools when it stops working."""
    if not is_enabled():
        return None
    if not is_configured():
        return None
    s = config.get_proxy_settings()
    picked_at = s.get("proxy_picked_at", "")
    if picked_at and not force:
        try:
            t = datetime.fromisoformat(str(picked_at).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - t).total_seconds() / 60
            if age_min < STALE_AFTER_MIN:
                return s.get("proxy_active_ip")
        except Exception:
            pass
    url = config.get_proxy_url()
    if url:
        _lat, _status = _probe(url, TEST_E2_URL, 6)
        if _lat is not None:
            return s.get("proxy_active_ip")
    best, msg = refresh_and_activate()
    if best:
        config.log(f"proxy pool: {msg}")
    return best["ip"] if best else None


def ensure_active(force=True):
    """Public 'I need a working proxy right now'. Live-checks the active proxy
    and auto-repools when it is down. Returns (best_or_None, message) — never
    claims success unless a proxy is actually verified working."""
    if not is_enabled():
        return None, "proxy pool disabled — running direct"
    if not is_configured():
        return None, "proxy pool not configured (set URL and key in Settings)"
    url = config.get_proxy_url()
    if url:
        _lat, _status = _probe(url, TEST_E2_URL, 6)
        if _lat is not None:
            return True, f"proxy verified live — {config.mask_proxy_url(url)}"
    best, msg = refresh_and_activate()
    if best:
        return best["ip"], msg
    return None, msg


def pool_summary():
    """Human-readable pool overview: counts + best + active."""
    if not is_configured():
        return {"configured": False, "message": "pool not configured"}
    try:
        rows = list_pool()
    except Exception as e:
        return {"configured": True, "message": f"pool unreachable: {str(e)[:80]}"}
    alive = [r for r in rows if r.get("e2_ok")]
    best = pick_best(rows) if alive else None
    return {
        "configured": True,
        "enabled": is_enabled(),
        "total": len(rows),
        "alive": len(alive),
        "best": {
            "ip": best["ip"], "port": best.get("port"),
            "latency_ms": best.get("latency_ms"),
        } if best else None,
        "active": active_proxy(),
    }
