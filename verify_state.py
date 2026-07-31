#!/usr/bin/env python3
"""Self-verification for the YouTube Mirror Bot.

The bot has full database access and uses the database as its single source
of truth. Every cycle it runs this module to CHECK its own state against the
database, flag everything inconsistent, and HEAL only the small, provable
inconsistencies (a log row proving an upload happened is not a guess). It
never invents state — which is what lets it run 24/7 without hallucinating.

In CI this is invoked by continuous_loop.py. Standalone health report:

    PROJECT_ID=2 python3 verify_state.py          # project 2 (auto-heal on)
    PROJECT_ID=2 python3 verify_state.py --no-fix # report only
    python3 verify_state.py --all                 # every project
"""
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import supabase_db

STALE_WORK_MIN = 45


def _now():
    return datetime.now(timezone.utc)


def _today():
    return _now().strftime("%Y-%m-%d")


def _clean_list(items):
    seen = set()
    out = []
    for x in items or []:
        x = (x or "").strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _norm_channel(raw):
    """Normalize a channel reference from a project's channels CSV into the
    canonical form used by channel_cursors (@handle or UC... id)."""
    raw = (raw or "").strip()
    m = re.search(r'@([\w\-\.]+)', raw)
    if m:
        return "@" + m.group(1)
    m = re.search(r'(UC[\w\-]{22,})', raw)
    if m:
        return m.group(1)
    return raw or None


class Verifier:
    def __init__(self, project_id="", owner="", fix=True):
        self.pid = str(project_id)
        self.owner = owner
        self.fix = fix
        self.results = []
        self.heal_count = 0
        self.log = print

    # ── plumbing ──────────────────────────────────────────────────────────

    def _record(self, name, status, message="", healed=False, details=None):
        self.results.append({
            "check": name,
            "status": status,
            "message": message,
            "healed": healed,
            "details": details or {},
        })
        if healed:
            self.heal_count += 1
        self.log(f"  [{status.upper():4s}] {name}: {message}")

    def _fail(self, name, message, details=None):
        self._record(name, "fail", message, False, details)

    def _warn(self, name, message, healed=False, details=None):
        self._record(name, "warn", message, healed, details)

    def _ok(self, name, message, details=None):
        self._record(name, "ok", message, False, details)

    def _state(self):
        return supabase_db.get_upload_state(project_id=self.pid)

    def _save_state(self, state):
        supabase_db.save_upload_state(state, project_id=self.pid)

    # ── checks ────────────────────────────────────────────────────────────

    def check_connectivity(self):
        try:
            supabase_db.get_setting("__verify_probe", None)
            self._ok("connectivity", "database reachable")
        except Exception as e:
            self._fail("connectivity", f"database unreachable: {e}")

    def check_project_config(self):
        try:
            project = supabase_db.get_project(self.pid)
        except Exception as e:
            self._fail("project_config", f"could not load project row: {e}")
            return
        if not project:
            self._fail("project_config", f"no project row for id {self.pid}")
            return
        problems = []
        if not project.get("github_repo"):
            problems.append("github_repo not set")
        if not project.get("yt_client_id") or not project.get("yt_client_secret") or not project.get("yt_refresh_token"):
            problems.append("youtube credentials missing on project row")
        try:
            per_day = int(project.get("uploads_per_day") or 0)
        except (TypeError, ValueError):
            per_day = 0
        if per_day < 1:
            problems.append(f"uploads_per_day invalid ({project.get('uploads_per_day')})")
        try:
            warmup_days = int(project.get("warmup_days") or 0)
        except (TypeError, ValueError):
            warmup_days = -1
        if warmup_days < 0:
            problems.append("warmup_days invalid")
        channels = [c.strip() for c in str(project.get("channels") or "").split(",") if c.strip()]
        if not channels:
            problems.append("no channels configured")
        if not project.get("proxy_supabase_url") or not project.get("proxy_supabase_key"):
            problems.append("proxy supabase not configured (downloads may fail)")
        if problems:
            self._warn("project_config", "; ".join(problems))
        else:
            self._ok("project_config",
                     f"{project.get('name')} — {len(channels)} channel(s), {per_day}/day")

    def check_run_lock(self):
        if not self._has("run_locks"):
            self._warn("run_lock", "run_locks table missing — apply schema.sql")
            return
        rows = supabase_db._request("GET", f"run_locks?project_id=eq.{self.pid}&select=owner,expires_at")
        if not rows:
            self._warn("run_lock", "no run lock present (bot may not be running)")
            return
        lock = rows[0]
        owner = lock.get("owner", "")
        if self.owner and owner == self.owner:
            self._ok("run_lock", f"lock held by this run ({owner})")
        elif self.owner:
            alive = supabase_db._lock_owner_alive(self.pid, owner)
            if alive:
                self._warn("run_lock", f"another run holds the lock ({owner})")
            else:
                self._fail("run_lock",
                           f"stale lock held by dead owner {owner} — acquire would have stolen it")
        else:
            self._ok("run_lock", f"held by {owner}" if owner else "no owner")

    def check_lock_cleanup(self):
        if not self.fix or not self._has("run_locks"):
            return
        try:
            removed = supabase_db.clear_expired_locks()
            if removed:
                self._warn("lock_cleanup", f"removed {removed} expired run lock(s)", healed=True)
            else:
                self._ok("lock_cleanup", "no expired locks")
        except Exception as e:
            self._warn("lock_cleanup", f"cleanup failed: {e}")

    def check_heartbeat(self):
        if not self._has("run_heartbeats"):
            self._warn("heartbeat", "run_heartbeats table missing — apply schema.sql")
            return
        hb = supabase_db.get_heartbeat(self.pid)
        if self.owner:
            try:
                supabase_db.update_heartbeat(project_id=self.pid, run_id=self.owner,
                                             status="running", message="verify pass")
            except Exception as e:
                self._warn("heartbeat", f"heartbeat update failed: {e}")
                return
        if not hb:
            self._warn("heartbeat", "no heartbeat recorded yet")
            return
        t = supabase_db._parse_ts(hb.get("last_seen"))
        if not t:
            self._warn("heartbeat", "heartbeat timestamp unparseable")
            return
        age_min = (_now() - t).total_seconds() / 60
        run_id = hb.get("run_id", "")
        if age_min > 60:
            self._warn("heartbeat", f"last heartbeat {age_min:.0f} min ago (run {run_id})")
        else:
            self._ok("heartbeat", f"run {run_id} alive — {age_min:.0f} min ago, iter {hb.get('iteration', 0)}")

    def check_warmup(self):
        state = self._state()
        if not state.get("warmup_start"):
            self._warn("warmup", "warmup never started (account_created/history missing)")
            return
        start = supabase_db._parse_ts(state.get("warmup_start"))
        if not start:
            self._warn("warmup", f"warmup_start unparseable: {state.get('warmup_start')}")
            return
        days = (_now().replace(tzinfo=None) - start.replace(tzinfo=None)).days
        try:
            project = supabase_db.get_project(self.pid)
            warmup_days = int((project or {}).get("warmup_days") or 0)
        except (TypeError, ValueError):
            warmup_days = 0
        expected_done = days >= warmup_days
        if state.get("warmup_complete") != expected_done:
            self._warn("warmup",
                       f"day {days}/{warmup_days}, complete={state.get('warmup_complete')} "
                       f"(expected {expected_done})")
        elif expected_done:
            self._ok("warmup", f"complete (day {days}/{warmup_days})")
        else:
            self._ok("warmup", f"day {days}/{warmup_days}")

    def check_dedup(self):
        """processed_hashes is the dedup key that stops re-uploads. Reconcile
        it against upload_logs: a log row PROVES the source was already
        mirrored, so any logged source missing from processed_hashes is
        appended (prevents the duplicate-reupload bug). Entries with no log
        and no mirror_state record are flagged (audit gap), not removed —
        removing dedup would risk re-uploading."""
        if not self._has("upload_logs"):
            self._warn("dedup", "upload_logs table missing — apply schema.sql")
            return
        state = self._state()
        processed = _clean_list(state.get("processed_hashes"))
        if processed != list(state.get("processed_hashes") or []):
            state["processed_hashes"] = processed
            self._save_state(state)
            self._warn("dedup", "processed_hashes had duplicates/empty entries — cleaned", healed=True)
        try:
            logs = supabase_db.get_upload_logs(limit=500, project_id=self.pid)
        except Exception as e:
            self._warn("dedup", f"could not load upload logs: {e}")
            return
        logged_sources = _clean_list(l.get("source_video_id") for l in logs if l.get("source_video_id"))
        missing = [s for s in logged_sources if s not in processed]
        if missing:
            if self.fix:
                processed = processed + missing
                state["processed_hashes"] = processed
                self._save_state(state)
                self._warn("dedup", f"added {len(missing)} logged source(s) to processed_hashes: {missing}",
                           healed=True)
            else:
                self._warn("dedup", f"{len(missing)} uploaded source(s) missing from processed_hashes: {missing}")
        pending = supabase_db.get_pending_hashes(project_id=self.pid)
        stale_pending = [h for h in pending if h in processed]
        if stale_pending:
            if self.fix:
                remaining = [h for h in pending if h not in processed]
                supabase_db.set_pending_hashes(remaining, project_id=self.pid)
                self._warn("dedup", f"dropped {len(stale_pending)} already-processed video(s) from queue: {stale_pending}",
                           healed=True)
            else:
                self._warn("dedup", f"{len(stale_pending)} processed video(s) still queued for upload: {stale_pending}")
        else:
            self._ok("dedup", f"{len(processed)} processed, {len(logged_sources)} logged sources, queue clean")

    def check_pending_queue(self):
        if not self._has("work_queue"):
            self._warn("pending_queue", "work_queue table missing — apply schema.sql")
            return
        pending = supabase_db.get_pending_hashes(project_id=self.pid)
        processed = _clean_list(self._state().get("processed_hashes"))
        items = supabase_db.get_work_queue(project_id=self.pid, limit=50, status="pending")
        pending_item_ids = {it.get("video_id") for it in items}
        for vid in pending:
            if vid in processed:
                continue
            if vid not in pending_item_ids:
                if self.fix:
                    supabase_db.add_work_item("detect", project_id=self.pid,
                                              video_id=vid, title="", status="pending")
                    self._warn("pending_queue", f"re-created missing work item for queued video {vid}",
                               healed=True)
                else:
                    self._warn("pending_queue", f"queued video {vid} has no pending work item")
                return
        for it in items:
            if it.get("video_id") in processed:
                if self.fix:
                    supabase_db.update_work_item(it["id"], status="done",
                                                 error="already processed — closed by verifier")
                    self._warn("pending_queue", f"closed stale pending item {it['id']} for processed video",
                               healed=True)
                else:
                    self._warn("pending_queue", f"stale pending item {it['id']} for processed video")
        self._ok("pending_queue", f"{len(pending)} queued, {len(items)} pending work item(s)")

    def check_today_quota(self):
        state = self._state()
        project = supabase_db.get_project(self.pid)
        try:
            max_per_day = int((project or {}).get("uploads_per_day") or 2)
        except (TypeError, ValueError):
            max_per_day = 2
        today_count = supabase_db.get_today_upload_count(_today(), project_id=self.pid)
        last_date = state.get("last_upload_date")
        if last_date == _today():
            if today_count >= max_per_day:
                self._ok("today_quota", f"quota reached ({today_count}/{max_per_day} today)")
            elif today_count == 0:
                self._warn("today_quota",
                           "state says uploaded today but zero log rows — logs may have been deleted")
            else:
                self._ok("today_quota", f"{today_count}/{max_per_day} uploaded today")
        else:
            if today_count > 0:
                self._warn("today_quota",
                           f"{today_count} upload(s) today but last_upload_date={last_date}")
            else:
                self._ok("today_quota", f"no uploads today (last {last_date})")

    def check_stale_work(self):
        if not self.fix or not self._has("work_queue"):
            return
        try:
            closed = supabase_db.close_stale_work_items(project_id=self.pid, stale_minutes=STALE_WORK_MIN)
            if closed:
                self._warn("stale_work", f"marked {closed} stale in_progress item(s) failed", healed=True)
            else:
                self._ok("stale_work", "no stale work items")
        except Exception as e:
            self._warn("stale_work", f"failed: {e}")

    def check_cursors(self):
        try:
            project = supabase_db.get_project(self.pid)
            channels = [_norm_channel(c) for c in
                        str((project or {}).get("channels") or "").split(",")]
            channels = [c for c in channels if c]
        except Exception:
            channels = []
        if not channels:
            self._warn("cursors", "no channels configured on project")
            return
        cursors = supabase_db.get_all_cursors(project_id=self.pid)
        missing = [c for c in channels if c not in cursors]
        if missing:
            self._warn("cursors", f"no cursor yet for: {missing}")
        else:
            self._ok("cursors", f"{len(channels)} channel cursor(s) present")

    def check_mirror_audit(self):
        if not self._has("mirror_state"):
            self._warn("mirror_audit", "mirror_state table missing — apply schema.sql")
            return
        try:
            logs = supabase_db.get_upload_logs(limit=500, project_id=self.pid)
            mirror_rows = supabase_db.get_all_mirror_states(project_id=self.pid)
        except Exception as e:
            self._warn("mirror_audit", f"load failed: {e}")
            return
        log_ids = {l.get("video_id") for l in logs if l.get("video_id")}
        no_log = [r for r in mirror_rows if r.get("mirrored_video_id") not in log_ids]
        if no_log:
            self._warn("mirror_audit",
                       f"{len(no_log)} mirror_state record(s) without an upload_log row (audit gap)")
        else:
            self._ok("mirror_audit", f"{len(logs)} log row(s), {len(mirror_rows)} mirror record(s) consistent")

    def check_alerts(self):
        if not self._has("alerts"):
            self._warn("alerts", "alerts table missing — apply schema.sql")
            return
        try:
            open_alerts = supabase_db.get_open_alerts(self.pid, limit=25)
        except Exception as e:
            self._warn("alerts", f"could not load alerts: {e}")
            return
        if open_alerts:
            self._warn("alerts", f"{len(open_alerts)} open alert(s): "
                                 + ", ".join(a.get("message", "") for a in open_alerts[:3]))
        else:
            self._ok("alerts", "no open alerts")

    # ── orchestration ─────────────────────────────────────────────────────

    def run_all(self):
        self.log(f"[verify] project {self.pid} — checking state against database")
        self.missing_tables = [t for t in (
            "run_heartbeats", "verify_checks", "alerts", "mirror_state",
            "work_queue", "run_locks", "upload_logs", "upload_state") if not supabase_db.table_exists(t)]
        if self.missing_tables:
            self._warn("schema",
                       f"table(s) missing: {self.missing_tables} — run schema.sql in the "
                       f"Supabase SQL editor", details={"missing": self.missing_tables})
        self.check_connectivity()
        if self.results and self.results[0]["status"] == "fail":
            return self.summarize()
        self.check_project_config()
        self.check_run_lock()
        self.check_lock_cleanup()
        self.check_heartbeat()
        self.check_warmup()
        self.check_dedup()
        self.check_pending_queue()
        self.check_today_quota()
        self.check_stale_work()
        self.check_cursors()
        self.check_mirror_audit()
        self.check_alerts()
        self._persist()
        self._resolve_fixed_alerts()
        return self.summarize()

    def _has(self, *tables):
        return not any(t in self.missing_tables for t in tables)

    def summarize(self):
        fails = sum(1 for r in self.results if r["status"] == "fail")
        warns = sum(1 for r in self.results if r["status"] == "warn")
        oks = sum(1 for r in self.results if r["status"] == "ok")
        self.log(f"[verify] {oks} ok, {warns} warn, {fails} fail, {self.heal_count} healed")
        return {"fails": fails, "warns": warns, "oks": oks, "healed": self.heal_count}

    def _persist(self):
        if not self._has("verify_checks"):
            return
        for r in self.results:
            try:
                supabase_db.record_verify_check(
                    project_id=self.pid, check_name=r["check"], status=r["status"],
                    message=r["message"], details=r["details"])
            except Exception:
                pass

    def _resolve_fixed_alerts(self):
        """Auto-resolve alerts for checks that now pass, so the alert list
        only ever shows real, current problems."""
        if not self.fix or not self._has("alerts", "verify_checks"):
            return
        ok_checks = {r["check"] for r in self.results if r["status"] == "ok"}
        try:
            for a in supabase_db.get_open_alerts(self.pid, limit=50):
                if a.get("check_name") in ok_checks:
                    supabase_db.resolve_alert(a["id"], by="bot:verify")
        except Exception:
            pass


def run_for(project_id, owner="", fix=True):
    v = Verifier(project_id=project_id, owner=owner, fix=fix)
    return v.run_all()


def main():
    args = sys.argv[1:]
    no_fix = "--no-fix" in args
    all_projects = "--all" in args
    pid = None
    if not all_projects:
        if "--project" in args:
            pid = args[args.index("--project") + 1]
        elif os.environ.get("PROJECT_ID"):
            pid = os.environ.get("PROJECT_ID")
        else:
            print("usage: PROJECT_ID=N python3 verify_state.py [--no-fix] | python3 verify_state.py --all")
            sys.exit(2)
    if not supabase_db.is_enabled():
        print("error: supabase not configured (SUPABASE_URL / SUPABASE_SERVICE_KEY)")
        sys.exit(2)

    if all_projects:
        projects = supabase_db.list_projects()
        total = {"fails": 0, "warns": 0, "oks": 0, "healed": 0}
        for p in projects:
            print(f"\n===== project {p['id']} — {p.get('name')} =====")
            res = run_for(p["id"], fix=not no_fix)
            for k in total:
                total[k] += res.get(k, 0)
        print(f"\n===== TOTAL: {total['oks']} ok, {total['warns']} warn, {total['fails']} fail, "
              f"{total['healed']} healed =====")
        sys.exit(1 if total["fails"] else 0)
    else:
        res = run_for(pid, fix=not no_fix)
        sys.exit(1 if res["fails"] else 0)


if __name__ == "__main__":
    main()
