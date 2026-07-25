# AGENTS.md — Session Progress Tracker

> **Rule:** After ANY code change, file edit, or significant work, update this file immediately.
> This prevents hallucination and ensures accurate progress tracking across sessions.

---

## Current State

- **Last updated:** 2026-07-25
- **Latest local commit:** `54b5cf7` fix: guard pages follow learn_more.php from raw HTML instead of force-navigating
- **Previous commit:** `76775f2` fix: relay step always() to survive job timeout
- **Local codebase status:** MODIFIED — AUTOMATION.md + AGENTS.md updated (unstaged)
- **Accounts:** main (@adittaya), second (@rtff5665)
- **CI status:** 4 consecutive successful runs, 1 in-progress. Relay working 24/7.
- **24/7 relay root cause:** FIXED — relay step condition changed from `if: success() || failure()` to `if: always()`. Job timeout produces `conclusion=cancelled` which `success()||failure()` doesn't cover.
- **Guard page root cause:** FIXED — when `learn_more.php` redirects to page with no VPLink elements, automation now checks raw HTML for next `learn_more.php` link and follows it instead of force-navigating back to vplink.in.

## Key Files Reference

| File | Lines | Status | Purpose |
|------|-------|--------|---------|
| `automation.py` | 3505 | OK | VPLink automation engine — all template handlers, PageMonitor, flow logic |
| `tui.py` | ~1162 | OK | Interactive Python TUI — 8 screens, encryption, dispatch, progress |
| `proxy_rotator.py` | ~300 | OK | Proxy rotation with Supabase pagination, blacklist, used tracking |
| `continuous.yml` | ~200 | OK | CI workflow — proxy rotation fix, no-proxy fallback, relay always() |
| `config.py` | ~100 | OK | Config management (Supabase, proxy settings) |
| `schema.sql` | - | OK | Database schema |
| `AUTOMATION.md` | ~558 | MODIFIED | Comprehensive automation system guide — blueprint-aligned |
| `AGENTS.md` | this file | MODIFIED | Session progress tracker |

## Architecture Summary

- **VPLink flow:** vplink.in/KEY -> JS redirect -> Article page (TP/CE/LINK1S template) -> learn_more.php -> next article -> ... -> get-link page -> destination URL
- **4 templates:** TP (timer), CE (step/count), LINK1S (countdown), getlink (destination)
- **Guard pages:** Pages in funnel with no VPLink elements — followed via raw HTML extraction
- **Relay system:** Each CI run dispatches next run via `repository_dispatch` (condition: `if: always()`)
- **Proxy system:** 3 proxy attempts + 1 no-proxy fallback, one IP per session
- **Timeouts:** AUTOMATION_HARD_TIMEOUT=900s, step timeout-minutes=15, bash timeout=880s

---

## What Has Been Done (All Sessions — Chronological)

### Phase 1: Initial Setup & Analysis
1. Full codebase analysis — understood project purpose, architecture, all files
2. Fetched latest remote commit and compared with local
3. Analyzed last 5 GitHub Actions workflow runs via API
4. Identified proxy failure patterns: `ERR_TUNNEL_CONNECTION_FAILED`, `vplink-no-redirect` stuck64s, `first-goto-error`
5. Created AGENTS.md for session progress tracking
6. Researched latest automation relay systems (2025-2026)
7. Built comprehensive TODO list for all fixes needed

### Phase 2: Core Automation Improvements
8-12. **proxy_rotator.py** — Added pagination to `fetch_proxies()`, `_fetch_state_keys()`, updated blacklist/used key fetching
13-15. **automation.py** — Simplified `do_get_link()`, added `hard_max` to AdaptiveTimeout, reduced adaptive timeouts
16-17. **continuous.yml** — Added `RELAY_TARGET_REPO` env var, updated relay curl
18. **manager/app.py** — Added `LOOP_TRIGGER_TOKEN` to secrets_map (was missing — root cause of cross-account failure)
19-26. **automation.py** — VPLink flow engine: do_get_link fast path, timer cookie injection, template detection updates, get_step_info, handle_article logging
27-36. **automation.py** — Future-proofing: fingerprint_page, handle_generic, PageMonitor (MutationObserver + Network Interceptors), adaptive max_url_visits=10, step progress tracking

### Phase 3: Post-Test Cleanup
37-41. Removed hardcoded article domain checks from proxy_rotator.py, proxy-rotator.js, discover.js. Disabled mid-session proxy rotation.

### Phase 4: Raw HTML Fallback + Funnel Progress Guard
42-61. **automation.py** — Added `_funnel_progress`, `get_raw_html()`, `detect_js_health()`, `find_learn_more_in_html()`, `extract_redirect_from_html()`, `looks_like_article_url()`. Modified `is_destination()` with 3 guards. Modified handlers with raw HTML fallbacks. Updated AUTOMATION.md.

### Phase 5: Deployment CI Overhaul (11 fixes)
62-63. **manager/app.py** — Full template clone, `auto_init: True`, `git init -b main`, `--force` push, `RELAY_TARGET_REPO` in secrets, `ensure_workflow_enabled()`, `verify_deployment_run()`, `validate_token_scopes()`, flash messages
64-67. **continuous.yml** — Per-repo concurrency group, `Validate key` step, `--break-system-packages`, relay early-exit/error handling/exit 1

### Phase 6: GitHub Real-Time Sync
68-70. **github_sync.py** — NEW FILE: GitHub-as-database module. **vplink247.py** — Added `cmd_sync()`. **manager/app.py** — Added `_auto_scan_account()`.

### Phase 7: OpenTUI React TUI + Web GUI
71-98. Created React TUI (`tui/`) and Web GUI (`web/`) with full management interfaces. Both since deleted in favor of Python TUI.

### Phase 8: Fresh Python TUI
124-127. Deleted `web/`, `tui/` (React), `manager/`, all `.js` files. Created `tui.py` — fresh interactive Python TUI, zero dependencies, pure stdlib. 8 screens: Accounts, Deploy, Remove, Sync, Status, Logs, Settings, Dispatch.

### Phase 9: TUI Bug Fixes (commits d1ef864, 82c8d7c)
128-143. Added `encrypt_secret()` (dual-mode RSA-OAEP-SHA1 + NaCl), `set_repo_secret()`, fixed deploy (broken encryption, duplicate creation, missing step_cb), fixed gh() crash, added screen_dispatch(), fixed remove/nuke error handling, fixed screen_sync/sync crash guards, fixed screen_deploy encryption check, fixed screen_logs (80 lines, 10 runs), fixed screen_status (multi-account), fixed screen_accounts (deployment count), added VPLINK_KEY default, added named constants, fixed template caching (git pull), fixed deploy partial failure (_cleanup_repo), fixed token/secret visibility, fixed rate-limit handling, fixed local cleanup, added validate_repo_name(), replaced hardcoded timeouts.
152-154. Fixed NameError/KeyError crash guards in screen_sync, screen_remove, screen_status.
155-159. Added `load_legacy_config()`, `get_supabase_creds()`. Fixed deploy credentials from legacy config. Added SUPABASE_URL empty check. Pushed SUPABASE secrets via API.
160-163. Added git config user.email/name + GIT_AUTHOR/COMMITTER env vars. Added normalize_key() for URL inputs.
164. Added LOOP_TRIGGER_TOKEN to deploy secrets (was missing — root cause of cross-account relay failure).

### Phase 10: Dead Code Cleanup (121 lines removed)
144-151. Removed duplicate mark_proxy_used(), unused test_proxy_batch_selenium()/get_rotation_index(), unused imports, dead proxy functions in config.py, unreachable code in handle_article(), unused variables, fixed wait_for_countdown(None), changed BIN to ~/.local/bin.

### Phase 11: CDP Recording Analysis & Automation Rewrite
167-174. Rewrote human_read() from scratch — keyboard-only scrolling (PageDown/ArrowDown dispatch events), removed all mouse movement/bezier curves. Fixed get_page_height(). Added 2nd click to do_get_link(). Removed human_mouse_move() from click. Reordered close_ad_overlay() to CDP-exact sequence. Force-render skips overlay elements. Reduced handle_tp() wait 60->35s.
118-123. Created test_cdp_flow.py. Added iframe close handling. Added #post-2500 > div click. Rewrote do_get_link() as click->check->retry loop.

### Phase 12: CSS Shell Detection & Proxy Rotation Fix
175-178. Added CSS shell detection (height>500, body_len<100) to handle_article() and post-redirect handler. Added report_proxy_failure() calls. Increased exhausted_cycles limit 3->5.
179-182. **continuous.yml CRITICAL FIX**: Proxy rotation bug — `${{ steps.proxy.outputs.proxy }}` expanded ONCE at parse time, all iterations used same proxy. Fixed by reading into `CURRENT_PROXY` shell variable. Added no-proxy fallback attempt.

### Phase 13: Timeout Increase
194-196. Step timeout 10->15min, bash timeout 580->880s, AUTOMATION_HARD_TIMEOUT 600->900s.

### Phase 14: 24/7 Relay Fix (commit 76775f2)
197. **continuous.yml CRITICAL FIX**: Relay step condition `if: success() || failure()` -> `if: always()`. Job timeout produces `conclusion=cancelled` which isn't covered by success()/failure(). Verified: vplink-ttrgg55 had only 1 run (cancelled at 15m18s, relay skipped). vplink-bugu has 8 runs (finishes within timeout, relay fires).

### Phase 15: Guard Page Flow Fix (commit 54b5cf7)
198-199. **automation.py**: (1) handle_article() — after all-false fingerprint wait loop, if `_funnel_progress > 0`, checks raw HTML for `learn_more.php` links via `find_learn_more_in_html()` and `extract_redirect_from_html()`, follows the flow. (2) Main loop exhausted handler — before force-navigating, checks raw HTML for `learn_more.php` when `_funnel_progress > 0`.

---

## CDP Recording Analysis

Recording: `/home/ubuntu/Documents/Recording 7_24_2026 at 11_21_29 PM.json` (KEY=ekor0)

- **315 steps, 18 clicks, 259 scroll keys, 0 mouse movements**
- Template sequence: Landing -> TP -> TP -> CE -> LINK1S -> get-link -> DESTINATION
- Domain changes: darkguruji.com -> srtak.com (across learn_more.php redirects)
- All transitions via `learn_more.php` JS redirects
- Ad dismissal BEFORE reading (CDP steps 4-8 before steps 9-80)
- Pure keyboard scrolling (PageDown/ArrowDown dispatch events)
- `#get-link` requires 2 clicks (first activates, second navigates)

---

## CI Test Results

- **4 consecutive successful runs** on main account (@adittaya)
- Latest successful run: 10m36s, destination captured
- Run in-progress at time of last check
- All 4 templates detected and handled correctly
- Relay chain working continuously (always() fix verified)

---

## Pending / Completed User Requests

- User wants: comprehensive flow engine that handles ANY VPLink-type variation ✅ DONE
- User wants: "comprehensively train a model for this so he can handle literally anything" ✅ DONE
- User wants: future-proof against element ID renames ✅ DONE
- User wants: adaptive step count (not fixed 3/3) ✅ DONE
- User wants: adaptive redirect chains (not fixed 1-2 hops) ✅ DONE
- User wants: real-time MutationObserver + Network Interceptors ✅ DONE
- User wants: deployment CI fix — automation works on personal but not other accounts ✅ DONE
- User wants: real-time GitHub-based sync system (repos = database) ✅ DONE
- User wants: comprehensive AUTOMATION.md and AGENTS.md update ✅ DONE

---

## TODO List (All Items)

### High Priority — All Complete
- [x] Proxy Pool Pagination
- [x] do_get_link() Fast Path + Full Rewrite
- [x] Cross-Account Dispatch + Secrets
- [x] PageMonitor (MutationObserver + Network Interceptors)
- [x] Behavioral Fingerprinting
- [x] Adaptive Flow (any step count, any redirect chain)
- [x] GitHub Sync System (repos = database)
- [x] Fresh Python TUI (zero deps, 8 screens)
- [x] CDP-verified automation rewrite (keyboard scrolling, 2-click get-link, ad order)
- [x] CSS shell detection + proxy failure reporting
- [x] Proxy rotation bug fix (shell variable)
- [x] No-proxy fallback attempt
- [x] Timeout increase (15min)
- [x] 24/7 relay fix (always() condition)
- [x] Guard page flow continuation (follow learn_more.php from raw HTML)

### Medium Priority — All Complete
- [x] Template detection updates
- [x] vplink-no-redirect timeout cap
- [x] Step info logging
- [x] is_article_page() fix
- [x] Strict button detection (isRealButton)
- [x] TUI bug fixes (encryption, deploy, crash guards, rate-limit, visibility)
- [x] Deploy credentials fix (legacy config fallback)
- [x] Git identity fix (env vars)
- [x] Dead code cleanup (121 lines removed)

### Low Priority — All Complete
- [x] Test do_get_link — verified in 5-cycle local run
- [x] Test PageMonitor — verified in live flow
- [x] AUTOMATION.md comprehensive update
- [x] AGENTS.md comprehensive update

---

## Notes

- Repo: `adittaya/workflow-vplink` (GitHub)
- Token provided by user for API access
- Proxy pool has ~500 proxies in Supabase, 90%+ are dead, only ~10 alive per rotation
- VPLink flow always uses the same system: only article headings/topics/domains change
- Domains cycle: darkguruji.com <-> srtak.com (and potentially others)
- Step count is variable (2, 3, 4, N) — automation handles any number
- Redirect chains are variable (1, 2, 3, 5 hops) — automation follows until article page
- Fresh TUI at `tui.py` — single file, zero deps, run with `python3 tui.py`
- All data stored in `~/.vplink247/` (accounts.json, deployments.json, settings.json)
- GitHub secrets encryption: NaCl sealed box for newer repos, RSA-OAEP-SHA1 for older repos
- Chromium: `/usr/bin/chromium` (150.0.7871.100), Python 3.12.3, chromedriver 150.0.7871.100
- User's working directory: `/home/ubuntu/work/workflow-vplink`
- Config path: `~/.config/vplink3/config.json` (Supabase creds, proxy settings)
- CI test key: `gbd1b` (URL: `https://vplink.in/gbd1b`)
