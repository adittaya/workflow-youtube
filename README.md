# YT VIDEO AUTOMATION

Manual YouTube upload tool: paste a video link, it downloads the video, runs
the audio/video processing pipeline (Demucs vocal separation, FFmpeg edits,
non-copyright BGM) to avoid Content ID, and uploads to your channel.

Runs on your machine using local JSON state files — **no GitHub or 24/7
daemon**. Cloud storage via Supabase remains available as an opt-in.

## Features

- **Manual upload**: `yt-auto upload URL` — link → process → title/comment/
  description prompts → publish (or save as private draft)
- **Video processing**: Demucs vocal separation (strips original music),
  FFmpeg edits (crop/speed/grain/brightness/fade), non-copyright BGM mix
- **Comments**: posts the shortened download link on the uploaded video
  (VPLink/CleanURI/TinyURL or plain URL)
- **Self-verification**: `yt-auto verify` checks state against the logs and
  heals only provable inconsistencies
- **Multi-account**: saved YouTube accounts with OAuth refresh-token health
  tracking; projects pick who uploads
- **Proxy support**: route downloads and YouTube uploads through a proxy from
  the TUI (`Settings → Proxy`) — for when YouTube blocks publishing from a
  server/data-centre IP. HTTP, HTTPS, SOCKS4 and SOCKS5, with a live
  connection test.

## Install via the Bootstrap Installer

**One-line full setup** (Linux/macOS; requires `curl` and Python 3.10+):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/adittaya/workflow-youtube/main/bootstrap.sh)
```

The installer handles everything: system + pip dependencies (apt/dnf/pacman/
zypper/brew/pkg/winget), installs the `yt-auto`, `YOUTUBE` and `installer`
commands, writes your config, rolls back on failure, and self-updates — with a
verify/doctor/uninstall suite.

```bash
# from a source checkout (or after the one-liner above):
installer install --dry-run          # plan only, no changes
installer doctor --fix                # diagnose + auto-fix
installer verify                      # check everything
installer uninstall                   # remove (keeps data unless --purge)
```

Full docs: [`installer/README.md`](installer/README.md).

## Quick Start (local mode)

Prerequisites: Python 3.10+, `ffmpeg`, and a Google Cloud OAuth client with the
YouTube Data API v3 enabled (Desktop app, consent screen published).

```bash
# 1. Install dependencies
pip3 install -r requirements.txt

# 2. Guided setup (YouTube credentials)
python3 yt_auto.py setup

# 3. OAuth login — get a refresh token (opens browser)
python3 yt_auto.py oauth

# 4. Upload a video
python3 yt_auto.py upload https://www.youtube.com/watch?v=...
```

Or launch the management TUI from anywhere:

```bash
YOUTUBE
```

Inside the TUI, **`[Q] Quick Deploy`** is the fastest way to publish: it walks
you through it one question at a time —

1. pick a saved YouTube account (it live-checks the login token first),
2. paste the video link,
3. for each of **title → description → comment**, say `y` to copy the exact
   value from the source video or `n` to paste your own,
4. enable proxy mode by typing `-y`,
5. it downloads and processes the video,
6. then it tests the proxy, uploads — and if the upload is blocked by the
   proxy, it automatically rotates to the next pool proxy and retries.

## CLI Reference

```
YOUTUBE                                       interactive management TUI (projects,
                                              accounts, doctor, DB connection,
                                              settings/proxy)
yt-auto upload <URL>                          interactive upload: link → process →
                                              title/comment/description prompts → publish
yt-auto setup                                 guided first-time configuration
yt-auto oauth                                 YouTube OAuth login (get refresh token)
yt-auto status [--json]                       current state summary
yt-auto logs [N] [--json]                     recent upload log entries
yt-auto verify [--no-fix]                     self-verification of state
yt-auto version
```

`--project <id>` selects a project (defaults to `$PROJECT_ID`).

## Proxy Settings

If YouTube rejects or stalls your uploads from a server (data-centre) IP, route
traffic through a proxy:

```bash
YOUTUBE   →   [5] Settings   →   NETWORK / PROXY
```

Set the proxy type (`http`, `https`, `socks4`, `socks5`), host, port, and
optional username/password, then **enable** it and press `[T] Test proxy` for a
live connection check. The proxy is then used for:

- the **YouTube upload itself** (videos, comments, thumbnails),
- video **downloads** (yt-dlp),
- OAuth login and shortener calls.

Proxy credentials are stored in the same settings store as everything else —
`settings.json` in local mode, or the Supabase `settings` table in cloud mode
(so they sync with your database). `doctor.py` verifies the proxy on every
`[3] Doctor` run and auto-disables it if it becomes unreachable.

## Proxy Pool

The **proxy pool** automates proxy selection from a separate Supabase project
that holds a `proxy_results` inventory (the "proxy database"). When enabled, it:

- reads the pool, live-tests every proxy (TCP + HTTPS through the proxy) and
  writes results back (`latency_ms`, `e2_ok`, `vplink_ok`, `verified`, `last_seen`),
- picks the **fastest working** proxy, activates it in the shared proxy
  settings, and marks it "used" in `proxy_state` (rotates after 24h),
- **auto-repools** before any upload/download: the active proxy is re-tested,
  and if it stops working the pool is refreshed and a new one is chosen.

Set it up in the TUI: `[5] Settings → PROXY POOL` — enable the pool, enter the
pool Supabase URL + key, then `[P] Refresh & test pool` to test everything and
activate the fastest live proxy. From the CLI:

```bash
yt-auto proxy refresh   # test the whole pool, activate fastest live one
yt-auto proxy status    # pool overview (total/alive/best/active)
```

Pool credentials come from the settings store (local or cloud) or the
`PROXY_POOL_URL` / `PROXY_POOL_KEY` environment variables.

## Video Processing Pipeline

```
Download → Demucs vocal separation → FFmpeg edits → Non-copyright BGM mix → Upload
```

- **Demucs** separates vocals from the original music, which is discarded
  (graceful fallback to the original audio if it fails)
- **5 edit presets**: random crop, speed change, film grain, brightness,
  fade in/out (crop auto-scales to source resolution)
- **BGM**: a non-copyright track is mixed under the vocals at a low volume
  (falls back to vocals-only if unavailable)
- Downloads use the `android` yt-dlp client (avoids bot checks)

## State & Files

Everything lives in `~/.yt-mirror/` (override with `YT_DATA_DIR`):

| File | Purpose |
|------|---------|
| `config.json` | YouTube credentials, shortener config |
| `accounts.json` | Saved YouTube accounts |
| `settings.json` | Title/comment/description templates, shortener, proxy config |
| `upload_state.json` | Total uploaded, last upload, processed hashes |
| `daily_log.json` | Upload audit trail |
| `store/` | Local tables (projects, upload logs, alerts) |

All writes are atomic (`mkstemp` + rename, `0600`).

## Cloud Mode (opt-in)

Set `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` (or use the TUI's `[4]` Database
connection) and the same code persists to Supabase instead of local JSON. The
TUI (`python3 tui.py`) is hybrid — it runs on local JSON files by default and
manages cloud projects/accounts once a Supabase connection is set.

## Security

- YouTube refresh tokens and API keys are stored locally with `0600` perms and
  never committed. Runtime state files are gitignored.
- If a key ever leaks into a public repo, **rotate it** (the history rewrite
  cannot un-leak it) and scrub the history before pushing again.
