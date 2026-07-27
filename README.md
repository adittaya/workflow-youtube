# YouTube Mirror Bot

24/7 YouTube channel mirroring — monitors target channels, mirrors new uploads to your channel with download links.

## What It Does

1. **Monitors** target YouTube channels for new uploads (every 15 min)
2. **Downloads** video + thumbnail via yt-dlp
3. **Re-uploads** to your channel with modified title, description, tags
4. **Posts comment** with shortened download link, pins it
5. **Tracks state** to avoid duplicate mirrors

## Setup

### 1. Google Cloud Console

- Create project → Enable YouTube Data API v3
- OAuth consent screen → External → Publish App
- Create OAuth client (Desktop App) → download `client_secrets.json`

### 2. Get Refresh Token

```bash
pip install google-auth-oauthlib google-api-python-client
python3 get_refresh_token.py client_secrets.json
```

### 3. GitHub Secrets

Add to your repo → Settings → Secrets:

| Secret | Value |
|--------|-------|
| `YT_CLIENT_ID` | From step 2 |
| `YT_CLIENT_SECRET` | From step 2 |
| `YT_REFRESH_TOKEN` | From step 2 |
| `SHORTENER_API_KEY` | (Optional) URL shortener API key |
| `SHORTENER_API_URL` | (Optional) URL shortener endpoint |

### 4. Add Channels

Edit `~/.yt-mirror/channels.json`:

```json
{
  "@TargetChannel": {
    "url": "https://www.youtube.com/@TargetChannel",
    "alias": "Target Channel",
    "enabled": true
}
```

### 5. Enable Workflow

Go to GitHub Actions → Enable "YouTube Mirror Bot"

## Configuration

Config stored at `~/.yt-mirror/config.json`:

```json
{
  "mirror_title_prefix": "",
  "mirror_description_suffix": "\n\nOriginal video by {channel}",
  "comment_text": "Download link: {url}",
  "privacy_status": "public",
  "category_id": "22",
  "dry_run": false
}
```

## Architecture

```
Channel → monitor.py (polls uploads playlist)
              ↓ new video
         mirror.py (orchestrator)
              ↓
    ┌─────────┼─────────┐
    ↓         ↓         ↓
download   shortener  youtube_api
(yt-dlp)  (URL short) (upload+comment)
```

## Files

| File | Purpose |
|------|---------|
| `mirror.py` | Main engine — orchestrates the full pipeline |
| `youtube_api.py` | YouTube Data API v3 wrapper |
| `monitor.py` | Channel polling for new videos |
| `shortener.py` | URL shortener integration |
| `download_helpers.py` | yt-dlp video/thumbnail download |
| `config.py` | Config + state management |
| `get_refresh_token.py` | One-time OAuth setup |
| `youtube.yml` | GitHub Actions workflow |

## API Quota

- Upload: 1600 units/day (max ~6 videos)
- Comments: ~50 units
- Channel list: ~1 unit
- Playlist items: ~1 unit
