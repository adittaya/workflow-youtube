# YT VIDEO AUTOMATION

Local-first YouTube mirror bot: monitors target channels, detects new uploads,
and mirrors them to your own channel with the same audio/video processing
pipeline (Demucs vocal separation, FFmpeg edits, non-copyright BGM) to avoid
Content ID.

Runs entirely on your machine using local JSON state files — **no Supabase or
GitHub required**. Cloud mode (Supabase + GitHub Actions 24/7) remains
available as an opt-in.

## Features

- **Detect → Process → Upload** loop every 15 minutes
- **Local daemon**: `yt-auto run` runs continuously (detect → upload → sleep),
  schedulable with `cron` or `nohup`
- **Single pass**: `yt-auto run --once` for one detect+upload+verify cycle
- **Video processing**: Demucs vocal separation (strips original music),
  FFmpeg edits (crop/speed/grain/brightness/fade), non-copyright BGM mix
- **Comments**: posts the shortened download link on the mirrored video
  (VPLink/CleanURI/TinyURL or plain URL)
- **Self-verification**: `yt-auto verify` checks state against the logs and
  heals only provable inconsistencies
- **Run-lock guard**: parallel runs are serialized via a local lock with
  heartbeat + stale-owner stealing

## Quick Start (local mode)

Prerequisites: Python 3.10+, `ffmpeg`, and a Google Cloud OAuth client with the
YouTube Data API v3 enabled (Desktop app, consent screen published).

```bash
# 1. Install dependencies
pip3 install -r requirements.txt

# 2. Guided setup (YouTube credentials + channels)
python3 yt_auto.py setup

# 3. OAuth login — get a refresh token (opens browser)
python3 yt_auto.py oauth

# 4. Check status
python3 yt_auto.py status

# 5. Run the daemon (cron/no block of this terminal)
nohup python3 yt_auto.py run > ~/.yt-mirror/daemon.log 2>&1 &
```

Or as a one-off:

```bash
python3 yt_auto.py run --once
```

## CLI Reference

```
yt-auto run [--once] [--dry-run] [--duration H]   continuous daemon / single pass
yt-auto setup                                     guided first-time configuration
yt-auto oauth                                     YouTube OAuth login
yt-auto channels list|add <url> [alias]|remove <id>
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
- Uploads use the `android` yt-dlp client (avoids bot checks) through a
  rotating proxy pool when configured

## State & Files

Everything lives in `~/.yt-mirror/` (override with `YT_DATA_DIR`):

| File | Purpose |
|------|---------|
| `config.json` | YouTube credentials, shortener config |
| `channels.json` | Tracked channels |
| `settings.json` | Upload schedule / per-day quota / warmup settings |
| `upload_state.json` | Warmup, total uploaded, processed/pending hashes |
| `daily_log.json` | Upload audit trail |
| `state.json` | Mirror records + stats |
| `store/` | Local tables (projects, cursors, work queue, run locks, alerts) |

All writes are atomic (`mkstemp` + rename, `0600`).

## Cloud Mode (opt-in)

Set `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` and the same code persists to
Supabase and can be deployed to GitHub Actions for 24/7 operation (see
`.github/workflows/`). The `VPLINKYT` TUI (`python3 tui.py`) manages cloud
projects, OAuth and deploys.

## Security

- YouTube refresh tokens and API keys are stored locally with `0600` perms and
  never committed. Runtime state files are gitignored.
- If a key ever leaks into a public repo, **rotate it** (the history rewrite
  cannot un-leak it) and scrub the history before pushing again.
