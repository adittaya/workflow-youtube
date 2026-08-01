# AGENTS.md — YT VIDEO AUTOMATION

## Current State

- **Project:** YT VIDEO AUTOMATION — manual YouTube upload tool. Paste a link,
  it runs Demucs vocal separation → FFmpeg edits → BGM mix to avoid Content ID,
  then uploads to your channel. No 24/7 automation, no GitHub, no channel
  mirroring — those systems were cut in the 2026-08 refactor.
- **Model:** **local-first by default** — runs on the user's machine via the
  `yt-auto` CLI with local JSON state in `~/.yt-mirror/`. No Supabase/GitHub
  required.
- **Cloud (opt-in):** setting `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` routes
  the same code through Supabase for storage. The TUI (`tui.py`) is hybrid —
  local JSON by default, cloud projects/accounts once a Supabase connection is
  set (`[4]` in the main menu).
- **Entry points:** `yt_auto.py` = main local CLI (`upload`/`setup`/`oauth`/
  `status`/`logs`/`verify`/`version`); `tui.py` = management TUI (hybrid
  local/cloud).

## Manual Run Model

- `python3 yt_auto.py upload <URL>` — interactive single upload: link →
  process → title/comment/description prompts → publish (or private draft)
- `python3 yt_auto.py setup` — guided first-time config; `oauth` —
  refresh-token login (7-day expiry; re-run before expiry)
- `python3 yt_auto.py status`/`logs`/`verify` — inspection and self-healing

## Architecture

- `supabase_db.py` — single DB layer with **two backends**: Supabase REST when
  `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` are set, otherwise a local JSON store.
  Existing callers are untouched (transparent). Local tables:
  - Legacy-format files (shared with `config.py`/`daily_uploader.py` readers):
    `upload_state.json`, `daily_log.json`, `settings.json`
  - Canonical tables under `~/.yt-mirror/store/`: `projects`, `upload_logs`,
    `alerts`, `verify_checks`
  - `is_enabled()` stays `False` in local mode; `table_exists()` returns True
  - Legacy DB helpers for the cut systems (run locks, work queue, channel/
    cursor, mirror tables, mirror stats) were removed in the 2026-08 cleanup —
    do not reintroduce them without also restoring their schema.
- `yt_auto.py` — CLI: `upload`, `setup`, `oauth`, `status`, `logs`, `verify`,
  `version`
- `config.py` — local config/state helpers (`~/.yt-mirror/`), atomic `0600`
  writes (`mkstemp` + rename). `load_channels()`/`save_channels()` are no-op
  stubs (mirroring is gone)
- `daily_uploader.py` — `process_video()` pipeline hook + `upload_daily()`
  (force=True); upload audit via `upload_logs`/`daily_log.json`
- `download_helpers.py` — yt-dlp download (`android` client), iterates
  `WORKING_PROXIES` on failure; `--cookies` from `YT_COOKIES`/`YT_COOKIES_FILE`
- `verify_state.py` — self-verification/healing; checks credentials, dedup and
  alerts only (24/7 checks were removed)
- `doctor.py` — project/account checks with auto-fixes (OAuth token live test,
  shortlink/comment field fuzzing); GitHub/channel/schedule/proxy checks removed
- `youtube_api.py` — YouTube Data API v3 wrapper (`MAX_RETRIES=3`,
  retriable statuses 500/502/503/504)
- `video_processor.py` / `audio_separator.py` / `bgm_manager.py` — processing
  pipeline with graceful degradation
- `shortener.py` — VPLink/CleanURI/TinyURL/generic; falls back to the original URL

## State Management

- `upload_state.json` — total_uploaded, last_upload_date, processed_hashes,
  pending_hashes, yt_client_id (warmup fields removed)
- `upload_logs` / `daily_log.json` — audit trail of upload attempts (dedup
  source)
- Dedup: `processed_hashes` + `upload_logs`
- `verify_state.py` heals only provable inconsistencies (a log row proving an
  upload is not a guess)

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

## Known Gaps / Next Steps

- `YT_COOKIES` secret was dead (no `--cookies` passed) — now wired; verify on a
  live download
- `install.sh` still points at the old repo URL; update `REPO_URL` once the
  new git is connected
- No tests/lint CI on the code itself
