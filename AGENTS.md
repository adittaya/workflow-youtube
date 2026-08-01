# AGENTS.md — YT VIDEO AUTOMATION

## Current State

- **Project:** YT VIDEO AUTOMATION — monitors target channels, mirrors new uploads to own channel with processing (Demucs vocal separation → FFmpeg edits → BGM mix) to avoid Content ID
- **Model:** **local-first by default** — runs on the user's machine via the `yt-auto` CLI with local JSON state in `~/.yt-mirror/`. No Supabase/GitHub required
- **Cloud (opt-in):** setting `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` routes the same code through Supabase, deployable to GitHub Actions 24/7 via `.github/workflows/youtube.yml` / `score.yml`. The `VPLINKYT` TUI (`tui.py`) manages cloud projects/OAuth/deploys
- **Entry points:** `yt_auto.py` = main local CLI; `tui.py` = legacy cloud TUI; `continuous_loop.py` = daemon loop shared by both

## Local Run Model

- `python3 yt_auto.py run` — continuous detect→upload→sleep loop (5.5h per run by default; `--duration H` overrides). Schedulable via cron/nohup:
  ```
  nohup python3 yt_auto.py run > ~/.yt-mirror/daemon.log 2>&1 &
  ```
- `python3 yt_auto.py run --once` — single detect+upload+verify pass (acquires/releases the run lock)
- `python3 yt_auto.py setup` — guided first-time config; `oauth` — refresh-token login; `status`/`logs`/`verify`/`channels` — inspection and management

## Architecture

- `supabase_db.py` — single DB layer with **two backends**: Supabase REST when
  `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` are set, otherwise a local JSON store.
  Existing callers are untouched (transparent). Local tables:
  - Legacy-format files (shared with `config.py`/`daily_uploader.py` readers):
    `upload_state.json`, `daily_log.json`, `state.json`, `settings.json`
  - Canonical tables under `~/.yt-mirror/store/`: `projects`, `channel_cursors`
    (`cursors.json`), `work_queue`, `run_locks`, `run_heartbeats`, `alerts`,
    `verify_checks`
  - `is_enabled()` stays `False` in local mode; `table_exists()` returns True
- `yt_auto.py` — CLI: `run`, `once`, `setup`, `oauth`, `channels`, `status`,
  `logs`, `verify`, `version`
- `config.py` — local config/state helpers (`~/.yt-mirror/`), atomic `0600`
  writes (`mkstemp` + rename)
- `continuous_loop.py` — detect→upload→sleep loop; lock + heartbeat; verify per
  iteration. Download failures **re-queue** the video (never drops)
- `daily_uploader.py` — warmup/scheduling, cursor tracking, quota from
  `upload_logs` (authoritative), tz-safe arithmetic
- `download_helpers.py` — yt-dlp download (`android` client), iterates
  `WORKING_PROXIES` on failure; `--cookies` from `YT_COOKIES`/`YT_COOKIES_FILE`
- `verify_state.py` — self-verification/healing; local mode reads channels from
  `channels.json` and skips cloud-only project checks
- `youtube_api.py` — YouTube Data API v3 wrapper (`MAX_RETRIES=3`,
  retriable statuses 500/502/503/504)
- `video_processor.py` / `audio_separator.py` / `bgm_manager.py` — processing
  pipeline with graceful degradation
- `shortener.py` — VPLink/CleanURI/TinyURL/generic; falls back to the original URL

## State Management

- `upload_state.json` — warmup_start, warmup_complete, total_uploaded,
  last_upload_date, processed_hashes, pending_hashes, yt_client_id
- `channel_cursors` — per-channel last_video_id for new-video detection
- `upload_logs` / `daily_log.json` — audit trail of upload attempts (the
  authoritative source for quota + dedup)
- Triple dedup: `processed_hashes` + `upload_logs` + `mirror_state`
- `verify_state.py` heals only provable inconsistencies (a log row proving an
  upload is not a guess)

## CI Workflow (cloud mode only)

Self-sustaining 24/7 chain: `continuous_loop.py` queues a follow-up run via
`gh workflow run` *after* acquiring the run lock; workflow-level `concurrency`
(`cancel-in-progress: false`) serializes runs; cron `0 */6 * * *` is only a
fallback. Do not flip `cancel-in-progress` to `true` — it breaks the chain.

## Testing / Verification

- `python3 -m py_compile *.py` — all modules compile
- `python3 yt_auto.py verify` — self-check (local); `yt-auto status --json` — inspect state
- Local backend smoke tests run against a throwaway `YT_DATA_DIR` to avoid touching real state
- No test framework is installed; verification is manual via the CLI

## Security

- Runtime state files are gitignored and **must never be committed**. The
  current history was scrubbed of `shortlink_keys.json` / `upload_state.json`
  (filter-branch); keep it that way.
- Rotate any key that ever reached a public repo — history rewrite does not
  un-leak it.
- `config.json`/`accounts.json` hold refresh tokens — keep `0600`.
- `github_api.py` `create_repo` currently hardcodes `"private": False` — revisit
  before any deploy work.

## Known Gaps / Next Steps

- `YT_COOKIES` secret was dead (no `--cookies` passed) — now wired; verify on a
  live download
- `install.sh` still points at the old repo URL and installs `VPLINKYT`; update
  `REPO_URL`/binary once the new git is connected
- TUI (`tui.py`) is not yet branded; cloud-only paths unchanged
- No tests/lint CI on the code itself; deploys push straight to production
