# AGENTS.md — YouTube Mirror Bot

## Current State

- **Project:** YouTube Mirror Bot — monitors target channels via Supabase, mirrors to own channel
- **GitHub:** `adittaya/workflow-shorturl-yt` (private); deployed to `joymoy767/main`
- **Supabase:** Multi-project management via `upload_state`, `channel_cursors`, `upload_logs` tables
- **CI cron:** `0 */6 * * *` (every 6h) — single long-running job (360min timeout) loops detect→upload for 5.5h continuously

## CI Workflow

1. **Warmup** (once) — auto-starts/completes based on elapsed time; tracks `yt_client_id` for account changes
2. **Fetch proxy** (once) — queries proxy Supabase (`bytemjjijgwwcrxlgutf`) for VPLINK-verified residential proxies, speed-tests each (5s HTTP timeout), stores top 10 working in `WORKING_PROXIES` env var
3. **Continuous loop** (~5.5h) — `continuous_loop.py` runs detect→upload→sleep every 15 minutes:
   - **Detect** — polls each channel's uploads playlist, compares with `channel_cursors.last_video_id`, collects new IDs into `pending_hashes` (oldest-first), updates cursor
   - **Upload** (if cooldown allows) — pops oldest from `pending_hashes`, downloads with yt-dlp (`android` client through `--proxy`), processes via `daily_uploader`, uploads; fails → tries next proxy, then re-queues if all proxies exhausted
   - **Sleep** 15 minutes, repeat until ~5.5h elapsed

## Key Files

| File | Purpose |
|------|---------|
| `tui.py` | Multi-project TUI with auto-suggest, OAuth, warmup, deploy, dispatch |
| `supabase_db.py` | Supabase REST wrapper with `resolution=merge-duplicates` Prefer header; retry with backoff |
| `daily_uploader.py` | Warmup/scheduling, cursor tracking, tz-safe datetime arithmetic |
| `download_helpers.py` | yt-dlp download with `--extractor-args youtube:player_client=android`; iterates `WORKING_PROXIES` on failure |
| `github_api.py` | Repo CRUD, git push (remove origin before add), secret encryption, dispatch |
| `config.py` | Channels/accounts/state via Supabase |
| `youtube_api.py` | YouTube Data API v3 wrapper |
| `continuous_loop.py` | Continuous 5.5h detect→upload loop |
| `.github/workflows/youtube.yml` | 6h cron + workflow dispatch |

## State Management

- `upload_state` — warmup_start, warmup_complete, total_uploaded, last_upload_date, processed_hashes, pending_hashes, yt_client_id
- `channel_cursors` — per-channel last_video_id for new video detection
- `upload_logs` — audit trail of upload attempts
- All fields stored as JSON in Supabase rows keyed by `project_id`

## Troubleshooting

- **409 on upsert:** ensure `Prefer: return=representation,resolution=merge-duplicates` header is sent
- **yt-dlp "bot" error:** android client flag `--extractor-args youtube:player_client=android` bypasses
- **Datetime error:** use `datetime.now(timezone.utc)` not `utcnow()`; strip tzinfo before subtraction
- **OAuth refresh:** expires every 7 days — re-run `[O]` in TUI before expiry
- **Git push "already exists":** `git remote remove origin` before `git remote add origin`