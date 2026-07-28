# YouTube Mirror Bot

Monitors target YouTube channels, mirrors new uploads to your channel with VPLink shortened download links in comments. Includes video processing (Demucs vocal separation, FFmpeg edits, non-copyright BGM) to avoid Content ID.

## One-Line Setup

```bash
git clone https://github.com/adittaya/workflow-shorturl-yt.git && cd workflow-shorturl-yt && bash install.sh
```

Then run `VPLINKYT` to open the management TUI.

> Local install is lightweight (~50MB). All video processing (torch, demucs, ffmpeg) runs on GitHub Actions runners.

## What It Does

1. **Monitors** channels every 6 hours (GitHub Actions cron)
2. **Detects** new uploads via uploads playlist
3. **Downloads** video + thumbnail (yt-dlp)
4. **Processes** — Demucs vocal separation, FFmpeg edits (crop/speed/grain/brightness/fade), non-copyright BGM mix
5. **Uploads** to your YouTube channel with modified title/description/tags
6. **Posts comment** with VPLink shortened download link (pinned, view-only)

## Setup

### Prerequisites
- Python 3.10+
- ffmpeg (`sudo apt install ffmpeg`)
- Google Cloud Console project with YouTube Data API v3 enabled
- OAuth consent screen (External, Published App)
- Desktop App OAuth client → download `client_secrets.json`

### First Time

```bash
# 1. Install
bash install.sh

# 2. Get OAuth token (run locally, opens browser)
python3 ~/.yt-mirror/src/get_refresh_token.py

# 3. Add channels to monitor
VPLINKYT  # → [C] Channels → [A] Add

# 4. Deploy to GitHub Actions
VPLINKYT  # → [D] Deploy → enter GitHub token + repo
```

### GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `YT_CLIENT_ID` | OAuth client ID |
| `YT_CLIENT_SECRET` | OAuth client secret |
| `YT_REFRESH_TOKEN` | OAuth refresh token |
| `CHANNELS` | Channels JSON (auto-set by deploy) |
| `SETTINGS` | Settings JSON (auto-set by deploy) |
| `SHORTLINK_KEYS` | VPLink API key (auto-set by deploy) |
| `GH_PAT` | GitHub PAT for state pushes |

## TUI Commands

```bash
VPLINKYT                    # Open management TUI
python3 ~/.yt-mirror/src/daily_mirror.py status    # Check warmup status
python3 ~/.yt-mirror/src/daily_mirror.py warmup --reset  # Reset warmup
```

## Account Warmup

New YouTube accounts need 14 days of watching/liking/subscribing before uploading. The bot tracks this automatically:

- **Day 0-14**: Warmup period — no uploads, just monitoring
- **Day 15+**: Uploads enabled — 1 video/day max, 18h gap between uploads
- Auto-resets if you change the OAuth account

## Video Processing Pipeline

```
Download → Demucs vocal separation → FFmpeg edits → Non-copyright BGM mix → Upload
```

- **5 edit presets**: random crop, speed change, film grain, brightness, fade in/out
- **Auto-scaling**: crop values auto-adjust if they exceed source resolution
- **CRF 28**: reasonable file sizes
- **BGM**: built-in lo-fi study track (extensible)

## Project Structure

```
├── mirror.py              # Main mirror engine
├── monitor.py             # Channel polling, new video detection
├── daily_uploader.py      # Warmup tracker, daily upload logic
├── daily_mirror.py        # CLI entry point
├── video_processor.py     # FFmpeg editing (5 presets)
├── audio_separator.py     # Demucs + FFmpeg vocal separation
├── bgm_manager.py         # Non-copyright BGM library
├── youtube_api.py         # YouTube Data API v3 wrapper
├── shortener.py           # VPLink/CleanURI/TinyURL/URL shorteners
├── download_helpers.py    # yt-dlp video/thumbnail download
├── config.py              # Config management, state persistence
├── github_api.py          # GitHub API wrapper
├── tui.py                 # Full management TUI
├── install.sh             # One-line installer
├── get_refresh_token.py   # OAuth PKCE token setup
└── .github/workflows/
    └── youtube.yml        # GitHub Actions (6h cron)
```

## License

Private — do not distribute.
