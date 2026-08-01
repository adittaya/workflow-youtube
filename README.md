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

## Install via the Bootstrap Installer

**One-line full setup** (Linux/macOS; requires `curl` and Python 3.10+):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/adittaya/workflow-youtube/main/bootstrap.sh)
```

The installer handles everything: system + pip dependencies (apt/dnf/pacman/
zypper/brew/pkg/winget), installs the `yt-auto` and `installer` commands,
writes your config, rolls back on failure, and self-updates — with a
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

Or use the management TUI:

```bash
python3 tui.py
```

## CLI Reference

```
yt-auto upload <URL>                              interactive upload: link → process →
                                                  title/comment/description prompts → publish
yt-auto setup                                     guided first-time configuration
yt-auto oauth                                     YouTube OAuth login (get refresh token)
yt-auto status [--json]                           current state summary
yt-auto logs [N] [--json]                         recent upload log entries
yt-auto verify [--no-fix]                         self-verification of state
yt-auto version
```

`--project <id>` selects a project (defaults to `$PROJECT_ID`).

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
| `settings.json` | Title/comment/description templates, shortener config |
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
