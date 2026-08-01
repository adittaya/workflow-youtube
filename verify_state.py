#!/usr/bin/env python3
"""Self-verification for YT VIDEO AUTOMATION.

Every run of `yt-auto verify` checks local state against the database (or
local store), flags everything inconsistent, and HEALS only the small,
provable inconsistencies (a log row proving an upload happened is not a
guess). It never invents state.

Standalone health report:

    PROJECT_ID=2 python3 verify_state.py          # project 2 (auto-heal on)
    PROJECT_ID=2 python3 verify_state.py --no-fix # report only
    python3 verify_state.py --all                 # every project
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import supabase_db


def _clean_list(items):
    seen = set()
    out = []
    for x in items or []:
        x = (x or "").strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


class Verifier:
    def __init__(self, project_id="", owner="", fix=True):
        self.pid = str(project_id)
        self.owner = owner
        self.fix = fix
        self.results = []
        self.heal_count = 0
        self.log = print

    # ── plumbing ──────────────────────────────────────────────────────────

    def _project(self):
        """Project row for this pid. In local-first mode the single local
        project row is used when the pid row itself is missing."""
        project = supabase_db.get_project(self.pid)
        if not project and not supabase_db.is_enabled():
            projects = supabase_db.list_projects()
            if projects:
                project = projects[0]
        return project

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
            project = self._project()
        except Exception as e:
            self._fail("project_config", f"could not load project row: {e}")
            return
        if not project:
            self._fail("project_config",
                       "no project row for id %s (run `yt-auto setup`)" % self.pid)
            return
        problems = []
        if not supabase_db.is_enabled():
            # Local-first mode: credentials come from local config (accounts.json),
            # not the project row — only presence of the local project is checked.
            if not project.get("name"):
                problems.append("project has no name")
            if problems:
                self._warn("project_config", "; ".join(problems))
            else:
                self._ok("project_config", f"local project '{project.get('name')}'")
            return
        if not project.get("yt_client_id") or not project.get("yt_client_secret") or not project.get("yt_refresh_token"):
            problems.append("youtube credentials missing on project row")
        if problems:
            self._warn("project_config", "; ".join(problems))
        else:
            self._ok("project_config", f"{project.get('name')} — credentials set")

    def check_dedup(self):
        """processed_hashes is the dedup key that stops re-uploads. Reconcile
        it against upload_logs: a log row PROVES the source was already
        uploaded, so any logged source missing from processed_hashes is
        appended (prevents the duplicate-reupload bug). Entries with no log
        are flagged (audit gap), not removed — removing dedup would risk
        re-uploading."""
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
        else:
            self._ok("dedup", f"{len(processed)} processed, {len(logged_sources)} logged sources consistent")

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
            "verify_checks", "alerts", "upload_logs", "upload_state") if not supabase_db.table_exists(t)]
        if self.missing_tables:
            self._warn("schema",
                       f"table(s) missing: {self.missing_tables} — run schema.sql in the "
                       f"Supabase SQL editor", details={"missing": self.missing_tables})
        self.check_connectivity()
        if self.results and self.results[0]["status"] == "fail":
            return self.summarize()
        self.check_project_config()
        self.check_dedup()
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
        elif not supabase_db.is_enabled():
            pid = ""
        else:
            print("usage: PROJECT_ID=N python3 verify_state.py [--no-fix] | python3 verify_state.py --all")
            sys.exit(2)

    if all_projects:
        projects = supabase_db.list_projects()
        if not projects:
            print("no projects configured")
            sys.exit(0)
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
