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
  set (`[4]` Database: the connect flow live-tests the URL/key via the REST
  API before saving — wrong keys and unreachable URLs are rejected with a
  clear message — then prints a data summary of projects/accounts/uploads/
  alerts; missing schema tables are listed with a "run schema.sql" warning; a
  fresh/empty database still connects and shows an empty state; `[D]` shows
  the summary anytime; local mode hints at `[4]` on the main menu; after a
  successful connect it asks **Auto-setup?** (y/N) — seeds every missing
  default setting via `config.seed_default_settings()` (all `tui_*` defaults
  from `TUI_SETTINGS_DEFAULTS` + proxy config from `PROXY_DEFAULTS`, never
  overwriting existing values, runtime proxy state excluded)).
- **Entry points:** `yt_auto.py` = main local CLI (`upload`/`setup`/`oauth`/
  `status`/`logs`/`verify`/`version`/`proxy`); `tui.py` = management TUI (hybrid
  local/cloud). Main menu is grouped into **Upload** (`[Q]` Quick Deploy guided
  upload — pick a saved account → live token check → video link → copy-or-custom
  title/description/comment → proxy-mode prompt (`y/N`) → download/process → test
  proxy → upload with proxy-pool re-rotation on failure; `[1]` Projects;
  `[6]` Batch run), **Accounts** (`[2]`), **Tools** (`[3]` Doctor, `[4]`
  Database, `[5]` Settings). Project menu is grouped into **Upload** (`[5]`
  Instant upload; `[6]` Bulk upload — one video → many accounts), **Setup**
  (`[1]` Configure, `[2]` YouTube account), **Tools** (`[3]` Doctor, `[4]`
  Status, `[H]` Upload history). Long lists (accounts/projects) paginate at 15
  rows with `[N]`/`[P]`; projects support `[R]` rename. Secret prompts show only
  a masked `********abcd` default — Enter keeps the value, never echoing the key.
  Configure fields `custom_description`/`custom_comment`/`mirror_description_suffix`
  accept **multi-line paste** (`_read_multiline`: every pasted line echoes on
  the terminal, a blank line — or `END` — finishes and saves; single-line
  `input()` silently cut long pastes at the first newline, which is why long
  descriptions appeared "not saved").
  UI strings prefer plain language over jargon (Google sign-in, "flagged by
  YouTube", short link service) with placeholder hints on inputs.
- **Bulk upload** (`[6]` per project): pick multiple saved accounts or "all",
  one video is downloaded once, then fired into every selected account with the
  project's pre-configured title/description/comment; fps + start/end trim are
  randomised per account via `bulk_fps_min/max` (default 20/25) and
  `bulk_trim_min/max` (default 10/20) so each copy differs; BGM is left as
  configured.
- **Batch run** (`[6]` in main menu or `[B]` in the Projects screen): select
  multiple projects (or "all"), tap done, and each project uploads its own
  stored `source_url` (field 1 in Configure) using its own linked account
  (from `account_id` or embedded creds) and its own custom fields; downloads
  rotate through the whole proxy pool with no retry cap (`retries=None`).
  **Scheduled uploads queue their comment**: the YouTube API refuses comments
  on private videos (403 forbidden), so when `publish_at` is set the comment
  is queued via `supabase_db.add_pending_comment` (JSON list in the settings
  table, works in both backends) and `daily_uploader.drain_pending_comments`
  posts it once the video is public — runs on TUI startup and
  `yt-auto comments`; attempts cap at 5, `commentsDisabled` drops
  immediately, deleted projects drop the entry with a log line.
  Cloud-only extra drain: `supabase/functions/post-pending-comments` (Edge
  Function, Deno TS) mirrors the Python drain so Supabase itself can post
  within ~1 min of publish — **deployed with verify_jwt=false** (the
  `sb_secret_...` key is not a JWT) and gated by the `X-Post-Secret` header
  matching the `FUNCTION_POST_SECRET` env secret; runs every minute via a
  **pg_cron job** calling `net.http_post` (pg_net rejects non-JSON bodies,
  so the OAuth refresh — form-urlencoded — must stay inside the function);
  project region is ap-southeast-1
  (`aws-0-ap-southeast-1.pooler.supabase.com` for psql); deploy via
  `supabase functions deploy post-pending-comments --project-ref zzxatvwjblfbaqzdxouw --no-verify-jwt`
  with `SUPABASE_ACCESS_TOKEN` set; setup SQL + test steps in the function
  README; validated live (cron run → HTTP 200 no-op, 403 without secret).
  Two optional questions before the run (Enter skips both): **videos per
  project** (1–5) — each extra copy is freshly processed with randomised
  fps/trim via `_bulk_random_overrides` so every upload is a distinct edit
  (copyright-safe); two more optional range questions let the user pick the
  randomise bounds per copy — **FPS range** (e.g. `22 28`) and **cut range**
  (e.g. `8 15`; answer `0`/`none` for **NO cut** — every copy keeps the full
  video, only FPS is randomised) — each copy draws fresh values inside those
  bounds (defaults 20–25 fps / 10–20s from settings) and the per-copy line
  shows the actual values; and **schedule publish** — uploads go up private with a
  `publishAt` RFC-3339 timestamp and YouTube auto-publishes them (threaded
  through `youtube_api.upload_video(publish_at=...)`; scheduling requires
  `privacyStatus=private`). Two schedule modes: **auto-spread (default)** —
  each copy gets its own slot every 6 hours from the current time
  (`slot_t0 + 6h*n`, displayed in local time, `timedelta` math in tui.py);
  or **one time** — all videos publish together at a chosen
  `YYYY-MM-DD HH:MM` local time.

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
  ordered rotation list (fastest first, skipping proxies marked used) with
  **no cap by default** (`limit=None` = whole pool); `mark_blocked()` parks a
  bot-checked proxy for `USED_TTL_HOURS`. Credentials from settings
  (`proxy_pool_url`/`proxy_pool_key`) or `PROXY_POOL_URL`/`PROXY_POOL_KEY` env.
  Wired into `youtube_api.get_client()` and `download_helpers.download_video()`.
- `daily_uploader.py` — `process_video()` pipeline hook + `upload_daily()`
  (force=True); upload audit via `upload_logs`/`daily_log.json`;
  `process_video(input_path, output_dir=None, overrides=None)` accepts
  per-upload `fps`/`trim_start`/`trim_end` overrides (bulk upload randomises
  these per account). `video_processor.apply_edits` clamps start/end trims
  so a short source (Shorts) never collapses to a 1s upload: trims are scaled
  down proportionally to keep ≥ max(3s, 40% of the source), logged via
  `config.log`. `video_processor.get_duration()` reads the video stream's own
  duration first (more reliable on fragmented MP4s) instead of `format` only
- `download_helpers.py` — yt-dlp download (`android` client,
  `formats=duplicate,missing_pot`). Shared `run_yt_dlp()` builds every yt-dlp
  invocation (cookies + proxy); `get_proxy_candidates()` orders proxies
  (configured Settings proxy first, then `WORKING_PROXIES` JSON, then
  `YT_PROXY`) and is merged with the whole `proxy_pool.candidate_urls()` list
  so downloads rotate through every pool proxy. `--cookies` from
  `YT_COOKIES`/`YT_COOKIES_FILE`/a `cookies_file` setting;
  `--cookies-from-browser` fallback from `YT_COOKIES_BROWSER`/`cookies_browser`.
  Detects YouTube bot-checks ("Sign in to confirm you're not a bot"), parks the
  flagged proxy via `mark_blocked()` and moves to the next one; raises
  `YouTubeBotCheck` only after every proxy was blocked — the TUI/CLI print an
  actionable message (add cookies or use residential proxies) instead of a
  generic network error. `download_video(url, output_dir=None, pool_retries=None)`
  has **no rotation/retry cap** with the pool enabled: when every proxy fails it
  refreshes the pool (`refresh_and_activate()`) and tries again; `pool_retries`
  caps the refresh rounds explicitly, `None` (default) = unlimited. Calls
  `proxy_pool.ensure_working()` before downloading when the pool is enabled
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
- `installer verify` also checks the **installed app copy is not stale** — it
  parses the installed `installer/version.py` and flags "re-install to update"
  when it is older than the current source version (so an old deployment is
  caught instead of silently running buggy code)
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
