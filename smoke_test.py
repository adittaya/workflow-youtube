#!/usr/bin/env python3
"""smoke_test.py — end-to-end smoke test for the Settings screens.

Runs every option in the TUI Settings menu and the proxy pool through real
code paths and reports PASS/FAIL per step. Settings writes go to a throwaway
data dir (local JSON) so real state is never touched; pool operations hit the
live pool database (read + write results, like the real app does).

Usage:
    python3 smoke_test.py            # run everything (includes live pool test)
    python3 smoke_test.py --quick    # skip the full 64-proxy refresh
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = tempfile.mkdtemp(prefix="yt-smoke-")
os.environ["YT_DATA_DIR"] = DATA_DIR
# Pool creds are captured before the pop below so the live pool sections [3]-[7]
# can still run when the caller provides them; app DB is forced local either way.
POOL_URL = os.environ.get("PROXY_POOL_URL", "") or ""
POOL_KEY = os.environ.get("PROXY_POOL_KEY", "") or ""
for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY",
          "PROXY_POOL_URL", "PROXY_POOL_KEY"):
    os.environ.pop(k, None)

import config
import proxy_pool
import doctor

PASS, FAIL = 0, 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {label}" + (f"  —  {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {label}" + (f"  —  {detail}" if detail else ""))


def main():
    quick = "--quick" in sys.argv
    print(f"\n  SMOKE TEST — Settings & Proxy Pool (data dir: {DATA_DIR})")
    print("  " + "-" * 60)

    print("\n  [1] Manual proxy settings round-trip")
    config.save_proxy_settings(
        proxy_enabled=True, proxy_protocol="http",
        proxy_host="10.0.0.5", proxy_port="3128",
        proxy_username="u", proxy_password="p")
    s = config.get_proxy_settings()
    check("save + read back", s.get("proxy_enabled") is True
          and s.get("proxy_host") == "10.0.0.5"
          and s.get("proxy_port") == "3128",
          "host/port/proto/user/pass stored")
    check("proxy URL built", config.get_proxy_url() == "http://u:p@10.0.0.5:3128",
          config.get_proxy_url())
    check("proxy URL masked", config.mask_proxy_url(config.get_proxy_url()) ==
          "http://u:***@10.0.0.5:3128", config.mask_proxy_url(config.get_proxy_url()))
    config.save_proxy_settings(proxy_enabled=False, proxy_host="", proxy_port="")
    check("clear proxy", config.get_proxy_url() == "", "settings cleared")

    print("\n  [2] Pool configuration")
    pool_url, pool_key = POOL_URL, POOL_KEY
    if pool_url and pool_key:
        config.save_proxy_settings(proxy_pool_url=pool_url, proxy_pool_key=pool_key)
        check("pool configured", proxy_pool.is_configured(), "URL + key in settings")
    else:
        print("  SKIP  pool sections [2]-[7] — set PROXY_POOL_URL/PROXY_POOL_KEY")
        rows = []

    print("\n  [3] Pool read (live pool DB)")
    if not (pool_url and pool_key):
        print("  SKIP  pool read (no pool configured)")
        rows = []
    else:
        try:
            rows = proxy_pool.list_pool()
            alive = [r for r in rows if r.get("e2_ok")]
            check("pool read", len(rows) > 0, f"{len(rows)} proxies, {len(alive)} alive")
        except Exception as e:
            check("pool read", False, str(e)[:80])
            rows = []

    print("\n  [4] Activate fastest from last results (no refresh)")
    if rows:
        best, msg = proxy_pool.activate_saved_best()
        if best:
            check("activate_saved_best", True, msg)
            s = config.get_proxy_settings()
            url = config.get_proxy_url()
            check("activation written to settings",
                  s.get("proxy_active_ip") == best["ip"]
                  and s.get("proxy_active_port") == str(best.get("port") or "")
                  and bool(url),
                  f"active={best['ip']}:{best.get('port')} url={url}")
            ok, lat, note = doctor.test_proxy(url)
            check("active proxy LIVE", ok, f"{lat}s ({note})")
        else:
            check("activate_saved_best", False, msg)
        proxy_pool.enable()  # same as the [7] toggle flow

    print("\n  [5] Full refresh + activate (live, the [P] flow)")
    if quick or not rows:
        print("  SKIP  full refresh (--quick or no pool configured) — last results used above")
    else:
        last = [None]

        def progress(done, total, label):
            print(f"\r    tested {done}/{total} — {label}{' ' * 20}", end="", flush=True)
            last[0] = label

        best, msg = proxy_pool.refresh_and_activate(progress=progress)
        print()
        if best:
            check("refresh_and_activate", True, msg)
            check("progress line well-formed",
                  last[0] is not None and ":" in last[0],
                  f"last: {last[0]}")
            check("pool enabled after refresh",
                  proxy_pool.is_enabled(),
                  "proxy_pool_enabled=True")
            s = config.get_proxy_settings()
            ok, lat, note = doctor.test_proxy(config.get_proxy_url())
            check("activated proxy LIVE", ok, f"{lat}s ({note})")
        else:
            check("refresh_and_activate", False, msg)

    print("\n  [6] ensure_active (used by Quick Deploy proxy mode)")
    if rows:
        ok, msg = proxy_pool.ensure_active(force=True)
        check("ensure_active", ok, msg)
    else:
        print("  SKIP  ensure_active (no pool configured)")

    print("\n  [7] Pool status summary")
    if rows:
        try:
            summary = proxy_pool.pool_summary()
            check("pool_summary shape",
                  summary.get("configured") is True and summary.get("total", 0) > 0,
                  f"{summary.get('alive')}/{summary.get('total')} alive, "
                  f"active={summary.get('active')}")
            check("pool_summary has best", bool(summary.get("best")),
                  str(summary.get("best")))
        except Exception as e:
            check("pool_summary", False, str(e)[:80])
    else:
        print("  SKIP  pool_summary (no pool configured)")

    print("\n  [8] Processing/BGM settings round-trip")
    config.save_tui_settings(fps=23, trim_start=15, trim_end=8, bgm_source="local")
    config.save_tui_setting("bgm_dir", "/tmp/bgm")
    t = config.load_tui_settings()
    check("fps/trim/bgm stored",
          int(t.get("fps") or 0) == 23 and int(t.get("trim_start") or 0) == 15
          and int(t.get("trim_end") or 0) == 8 and t.get("bgm_source") == "local",
          f"fps={t.get('fps')} trim={t.get('trim_start')}/{t.get('trim_end')} bgm={t.get('bgm_source')}")
    check("bgm_dir stored", t.get("bgm_dir") == "/tmp/bgm")

    print(f"\n  RESULT: {PASS} passed, {FAIL} failed")
    print()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())