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
  `status`/`logs`/`verify`/`version`/`proxy`); `tui.py` = management TUI (hybrid
  local/cloud) with a `[Q] Quick Deploy` guided upload (pick a saved account →
  live token check → video link → copy-or-custom title/description/comment →
  proxy-mode prompt (`-y`) → download/process → test proxy → upload with
  proxy-pool re-rotation on failure).

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
  writes (`mkstemp` + rename); proxy helpers: `get_proxy_settings()` /
  `save_proxy_settings()` (settings store: local `settings.json` or Supabase
  `settings` table), `get_proxy_url()` (auth-embedded URL), `mask_proxy_url()`,
  `apply_proxy_env()` (sets `http_proxy`/`https_proxy`/`ALL_PROXY` + `no_proxy`
  for localhost)
- `proxy_pool.py` — automated proxy pool manager: reads the pool DB
  (`proxy_results` inventory in a separate Supabase project), live-tests every
  proxy (TCP + HTTPS) writing results back, picks the fastest working one and
  activates it in the shared proxy settings; `ensure_working()` re-tests the
  active proxy and auto-repools on failure. `candidate_urls()` returns an
  ordered rotation list (fastest first, skipping proxies marked used) so the
  download path tries several proxies in a loop; `mark_blocked()` parks a
  bot-checked proxy for `USED_TTL_HOURS`. Credentials from settings
  (`proxy_pool_url`/`proxy_pool_key`) or `PROXY_POOL_URL`/`PROXY_POOL_KEY` env.
  Wired into `youtube_api.get_client()` and `download_helpers.download_video()`.
- `daily_uploader.py` — `process_video()` pipeline hook + `upload_daily()`
  (force=True); upload audit via `upload_logs`/`daily_log.json`
- `download_helpers.py` — yt-dlp download (`android` client,
  `formats=duplicate,missing_pot`). Shared `run_yt_dlp()` builds every yt-dlp
  invocation (cookies + proxy); `get_proxy_candidates()` orders proxies
  (configured Settings proxy first, then `WORKING_PROXIES` JSON, then
  `YT_PROXY`) and is merged with `proxy_pool.candidate_urls()` so downloads
  rotate through several pool proxies in a loop. `--cookies` from
  `YT_COOKIES`/`YT_COOKIES_FILE`/a `cookies_file` setting;
  `--cookies-from-browser` fallback from `YT_COOKIES_BROWSER`/`cookies_browser`.
  Detects YouTube bot-checks ("Sign in to confirm you're not a bot"), parks the
  flagged proxy via `mark_blocked()` and moves to the next one; raises
  `YouTubeBotCheck` only after every proxy was blocked — the TUI/CLI print an
  actionable message (add cookies or use residential proxies) instead of a
  generic network error. Calls `proxy_pool.ensure_working()` before downloading
  when the pool is enabled
- `bgm_manager.py` — `download_bgm_from_youtube()` reuses
  `download_helpers.run_yt_dlp()` (same extractor args, cookies, and proxy
  iteration as the main video path) so BGM downloads stop hitting bot-checks
  the video path already fixed
- `verify_state.py` — self-verification/healing; checks credentials, dedup and
  alerts only (24/7 checks were removed)
- `doctor.py` — project/account checks with auto-fixes (OAuth token live test,
  shortlink/comment field fuzzing); `test_proxy()` live proxy check + proxy
  config check in `check_project` (auto-disables via a `("setting", ...)` fix
  when the proxy is unreachable); GitHub/channel/schedule checks removed
- `youtube_api.py` — YouTube Data API v3 wrapper (`MAX_RETRIES=3`,
  retriable statuses 500/502/503/504); `get_client()` accepts optional explicit
  creds and builds an `AuthorizedHttp` over a proxy-routed `httplib2.Http`
  when a proxy is configured (`google_auth_httplib2`); calls
  `proxy_pool.ensure_working()` first when the pool is enabled
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

- Cookies (`YT_COOKIES`/`YT_COOKIES_FILE`) are wired through every yt-dlp call
  (video + BGM) and bot-check failures surface actionable guidance; still to be
  verified on a live download with real cookies from a datacenter proxy
- No tests/lint CI on the code itself
