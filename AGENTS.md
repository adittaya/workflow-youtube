# AGENTS.md — YouTube Mirror Bot

## Current State

- **Last updated:** 2026-07-27
- **Project:** YouTube Mirror Bot — monitors target channels, mirrors new uploads to own channel
- **Status:** Initial build complete, ready for OAuth setup and first test

## Architecture

```
Target Channel → monitor.py (polls uploads playlist)
                      ↓ new video detected
                 mirror.py (orchestrator)
                      ↓
         ┌───────────┼───────────┐
         ↓           ↓           ↓
  download_helpers  shortener   youtube_api
  (yt-dlp)         (URL short) (upload+comment)
```

## Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `mirror.py` | ~200 | Main engine: orchestrates monitor → download → upload → comment |
| `youtube_api.py` | ~200 | YouTube Data API v3 wrapper (upload, comments, channel, thumbnails) |
| `monitor.py` | ~80 | Channel polling — detects new videos via uploads playlist |
| `shortener.py` | ~100 | URL shortener integration (CleanURI, TinyURL, generic) |
| `download_helpers.py` | ~80 | yt-dlp video/thumbnail download |
| `config.py` | ~150 | Config management, channels, state persistence |
| `get_refresh_token.py` | ~50 | One-time OAuth setup script |
| `youtube.yml` | ~80 | GitHub Actions workflow (every 15min cron) |

## How It Works

1. **Monitor**: Every 15 min, poll each tracked channel's uploads playlist
2. **Detect**: Compare latest video ID against last known — new = needs mirroring
3. **Download**: yt-dlp downloads video (mp4) + thumbnail (jpg)
4. **Upload**: YouTube API uploads with modified title, description, tags
5. **Comment**: Posts download link comment (shortened URL), pins it
6. **State**: Tracks processed videos to avoid duplicates

## Setup Required

1. Google Cloud Console → YouTube Data API v3 enabled
2. OAuth consent screen → External → Published App
3. Desktop App OAuth client → download client_secrets.json
4. Run `python3 get_refresh_token.py` locally → get refresh token
5. Add 3 GitHub Secrets: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
6. Add channels to `~/.yt-mirror/channels.json`
7. Enable workflow in GitHub Actions

## YouTube API Quota

- Upload video: 1600 units
- Daily quota: 10,000 units
- Max uploads/day: ~6 videos
- Comment insert: ~50 units
- Channel list: ~1 unit
- Playlist items: ~1 unit

## Comment Section Control

- Posts comment with download link (shortened URL)
- Comment moderation: set to "heldForReview" so only approved comments appear
- Owner's comment always visible
- Comment text template: configurable in config.json

## Files Removed (VPLink)

All previous VPLink automation files have been removed:
- automation.py, tui.py, proxy_rotator.py, profile_generator.py
- install.sh (old), AUTOMATION.md, AUTOMATION_GUIDE.md
- continuous.yml (replaced with youtube.yml)
