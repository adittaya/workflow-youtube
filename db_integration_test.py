#!/usr/bin/env python3
"""db_integration_test.py — live integration test for EVERY supabase_db
operation and the account/project TUI flows, run against the cloud database.

Every operation uses names with spaces and special characters (the bug class
that crashed other machines: 'Car Parking Multiplayer' in a REST URL). All
rows created here are throwaway (prefixed TEST_) and cleaned up afterwards.

Usage: python3 db_integration_test.py
"""

import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = tempfile.mkdtemp(prefix="db-it-")
os.environ["YT_DATA_DIR"] = DATA_DIR
if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_KEY"):
    sys.exit("set SUPABASE_URL and SUPABASE_SERVICE_KEY (live cloud integration test)")

import supabase_db

PASS, FAIL = 0, 0
TEST_ACCT = "TEST Acct #1 & Co"
TEST_PROJ = "TEST Project Ω"
TEST_PID = "990001"


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {label}" + (f"  —  {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {label}" + (f"  —  {detail}" if detail else ""))


def raw_request(method, path, data=None):
    url = f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/{path.lstrip('/')}"
    if any(ch.isspace() for ch in url):
        url = "".join(urllib.parse.quote(c) if c.isspace() else c for c in url)
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "apikey": os.environ["SUPABASE_SERVICE_KEY"],
        "Authorization": f"Bearer {os.environ['SUPABASE_SERVICE_KEY']}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"[]")
    except urllib.error.HTTPError as e:
        raise AssertionError(f"{method} {path} -> HTTP {e.code} {e.read()[:150]}")


def main():
    print(f"\n  INTEGRATION TEST — cloud DB "
          f"({os.environ['SUPABASE_URL'].split('//')[1]})")
    print("  " + "-" * 60)

    print("\n  [1] Settings round-trip (values that used to be mangled)")
    supabase_db.set_setting("TEST_port", "3128")
    supabase_db.set_setting("TEST_flag", True)
    supabase_db.set_setting("TEST_obj", {"a": 1})
    check("string '3128' stays a string",
          supabase_db.get_setting("TEST_port") == "3128",
          repr(supabase_db.get_setting("TEST_port")))
    check("bool round-trip", supabase_db.get_setting("TEST_flag") is True)
    check("dict round-trip", supabase_db.get_setting("TEST_obj") == {"a": 1})
    raw_request("DELETE", f"settings?key=eq.TEST_port")
    raw_request("DELETE", f"settings?key=eq.TEST_flag")
    raw_request("DELETE", f"settings?key=eq.TEST_obj")

    print("\n  [2] Accounts — create/read/update/verify/delete with weird names")
    supabase_db.delete_account(TEST_ACCT)
    supabase_db.save_account(TEST_ACCT, {
        "client_id": "TEST-ID", "client_secret": "TEST-SECRET",
        "refresh_token": "", "channel_name": "TEST Channel", "status": "active"})
    got = supabase_db.get_account(TEST_ACCT)
    check("save + get (spaces & #)", got is not None and got["name"] == TEST_ACCT,
          f"name='{got['name'] if got else None}'")
    all_accts = supabase_db.get_all_accounts()
    check("listed", any(a["name"] == TEST_ACCT for a in all_accts),
          f"{len(all_accts)} accounts total")
    supabase_db.verify_account(TEST_ACCT, status="expired", last_error="test")
    check("verify_account writes status",
          supabase_db.get_account(TEST_ACCT).get("status") == "expired")
    supabase_db.increment_account_uploads(TEST_ACCT)
    check("increment uploads",
          supabase_db.get_account(TEST_ACCT).get("uploads_count") == 1)
    supabase_db.delete_account(TEST_ACCT)
    check("delete", supabase_db.get_account(TEST_ACCT) is None)

    print("\n  [3] Projects — create/update/delete with special chars")
    supabase_db.delete_project(TEST_PID)
    created = supabase_db.create_project(TEST_PROJ, source_url="https://youtu.be/aaaaaaaaaaa")
    pid = created["id"]
    check("create", created is not None and created["name"] == TEST_PROJ)
    got = supabase_db.get_project(pid)
    check("get by id", got is not None and got["name"] == TEST_PROJ)
    supabase_db.update_project(pid, source_url="https://youtu.be/bbbbbbbbbbb",
                               account_id=TEST_ACCT)
    got = supabase_db.get_project(pid)
    check("update fields", got["source_url"].endswith("bbbbbbbbbbb")
          and got["account_id"] == TEST_ACCT)
    check("listed in list_projects",
          any(p["id"] == pid for p in supabase_db.list_projects()))
    supabase_db.delete_project(pid)
    check("delete", supabase_db.get_project(pid) is None)

    print("\n  [4] Upload state — save/get round-trip")
    supabase_db.save_upload_state({
        "total_uploaded": 3, "last_upload_date": "2026-08-18",
        "processed_hashes": ["abc123", "def456"],
    }, project_id=TEST_PID)
    st = supabase_db.get_upload_state(TEST_PID)
    check("save/get", st.get("total_uploaded") == 3
          and st.get("processed_hashes") == ["abc123", "def456"],
          f"hashes={st.get('processed_hashes')}")
    raw_request("DELETE", f"upload_state?project_id=eq.{TEST_PID}")

    print("\n  [5] Upload logs — add/get/cleanup")
    supabase_db.add_upload_log({
        "upload_date": "2026-08-18", "video_id": "TESTVID1",
        "title": "TEST upload", "short_url": "https://vplink.in/TEST",
        "source_video_id": "src1", "source_channel": "TestChan",
    }, project_id=TEST_PID)
    logs = supabase_db.get_upload_logs(limit=5, project_id=TEST_PID)
    check("add + get", any(l.get("video_id") == "TESTVID1" for l in logs),
          f"{len(logs)} row(s) for project")
    raw_request("DELETE", f"upload_logs?project_id=eq.{TEST_PID}")

    print("\n  [6] Alerts + verify_checks")
    alerts = supabase_db.get_open_alerts(TEST_PID)
    check("get_open_alerts (empty project)", isinstance(alerts, list))
    supabase_db.record_verify_check(TEST_PID, "TEST_check", status="ok",
                                    message="integration test")
    supabase_db.record_verify_check(TEST_PID, "TEST_check", status="warn",
                                    message="upsert")
    checks = raw_request("GET", f"verify_checks?project_id=eq.{TEST_PID}&select=*")
    check("record_verify_check upserts on (project, check)",
          len(checks) == 1 and checks[0]["status"] == "warn",
          f"{len(checks)} row(s)")
    raw_request("DELETE", f"verify_checks?project_id=eq.{TEST_PID}")
    check("delete", raw_request("GET", f"verify_checks?project_id=eq.{TEST_PID}") == [])

    print("\n  [7] TUI account flow — delete unlinks projects")
    import tui
    supabase_db.save_account(TEST_ACCT, {"client_id": "X", "client_secret": "Y",
                                         "refresh_token": ""})
    tui._save_account(TEST_ACCT, {"client_id": "X", "client_secret": "Y",
                                  "refresh_token": ""})
    p = supabase_db.create_project("TEST Proj Linked", account_id=TEST_ACCT)
    tui._delete_account(TEST_ACCT)
    after = supabase_db.get_project(p["id"])
    check("project unlinked on account delete",
          after is not None and after.get("account_id") == "",
          f"account_id={after.get('account_id')!r}")
    supabase_db.delete_project(p["id"])

    print(f"\n  RESULT: {PASS} passed, {FAIL} failed")
    print()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())