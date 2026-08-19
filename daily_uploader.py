import json
import os
import re
import shutil
from pathlib import Path
from datetime import datetime, timezone

import config
import supabase_db
import youtube_api
import download_helpers
import video_processor
import audio_separator
import bgm_manager
import shortener

DATA_DIR = Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror")))
UPLOAD_STATE = DATA_DIR / "upload_state.json"
DAILY_LOG = DATA_DIR / "daily_log.json"


def load_upload_state():
    if supabase_db.is_enabled():
        state = supabase_db.get_upload_state(project_id=config.PROJECT_ID)
        state["pending_hashes"] = supabase_db.get_pending_hashes(project_id=config.PROJECT_ID)
        return state
    try:
        return json.loads(UPLOAD_STATE.read_text("utf-8"))
    except Exception:
        return {
            "account_created": None,
            "first_upload_date": None,
            "total_uploaded": 0,
            "last_upload_date": None,
            "last_upload_hour": None,
            "processed_hashes": [],
            "pending_hashes": [],
            "yt_client_id": "",
        }


def save_upload_state(state):
    if supabase_db.is_enabled():
        ph = state.get("pending_hashes")
        if ph is not None:
            supabase_db.set_pending_hashes(ph, project_id=config.PROJECT_ID)
        supabase_db.save_upload_state({k: v for k, v in state.items() if k != "pending_hashes"}, project_id=config.PROJECT_ID)
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_STATE.write_text(json.dumps(state, indent=2), "utf-8")


def load_daily_log():
    if supabase_db.is_enabled():
        logs = supabase_db.get_upload_logs(limit=100, project_id=config.PROJECT_ID)
        return {"uploads": [{
            "date": l.get("upload_date", ""),
            "time": l.get("upload_time", ""),
            "video_id": l.get("video_id", ""),
            "title": l.get("title", ""),
            "short_url": l.get("short_url", ""),
            "comment_id": l.get("comment_id", ""),
        } for l in logs]}
    try:
        return json.loads(DAILY_LOG.read_text("utf-8"))
    except Exception:
        return {"uploads": []}


def save_daily_log(log):
    if supabase_db.is_enabled():
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_LOG.write_text(json.dumps(log, indent=2), "utf-8")


def process_video(input_path, output_dir=None, overrides=None):
    # Every video is processed from scratch in its own scratch dir so the
    # next video never reuses the previous one's artifacts. The caller is
    # responsible for dedup (processed_hashes holds source video IDs, added
    # only AFTER a successful upload) — never mark a video processed here.
    # `overrides` may carry per-upload fps/trim_start/trim_end values (bulk
    # upload randomises these per account so every copy differs).
    input_path = Path(input_path)
    if output_dir is None:
        output_dir = input_path.parent / ".yt-proc"
    output_dir = Path(output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not video_processor.tools_ok():
        raise RuntimeError(
            "ffmpeg/ffprobe not installed — run `installer doctor` to fix dependencies")
    if not download_helpers.tools_ok():
        raise RuntimeError(
            "yt-dlp not installed — run `installer doctor` to fix dependencies")

    video_hash = video_processor.get_video_hash(input_path)
    config.log(f"processing fresh copy: {input_path.name} (hash {video_hash})")

    # Step 1: Demucs vocal separation — strip original music, keep vocals
    base_path = input_path
    if audio_separator.has_audio(input_path):
        config.log("  step 1: Demucs vocal separation (remove music, keep vocals)...")
        try:
            separated = audio_separator.remove_bgm_keep_vocals(
                input_path,
                output_video_path=output_dir / f"vocals_{input_path.name}",
                output_dir=output_dir / "stems",
            )
            base_path = Path(separated["video"])
        except Exception as e:
            config.log(f"  vocal separation failed ({e}) — falling back to original audio")
    else:
        config.log("  step 1: source has no audio track — skipping separation")

    # Step 2: FFmpeg edits (anti-Content-ID preset + fps + start/end trim)
    config.log("  step 2: applying video edits...")
    settings = config.load_tui_settings()

    def _int_setting(key, default):
        try:
            return int(float(settings.get(key) or default))
        except (TypeError, ValueError):
            return default

    def _override_int(key, default):
        if overrides and overrides.get(key) is not None:
            try:
                return int(overrides[key])
            except (TypeError, ValueError):
                pass
        return _int_setting(key, default)

    fps = _override_int("fps", 20)
    trim_start = _override_int("trim_start", 20)
    trim_end = _override_int("trim_end", 10)
    config.log(f"  edits: fps={fps}, trim {trim_start}s from start, {trim_end}s from end")
    edited_path = output_dir / f"edited_{input_path.name}"
    video_processor.apply_edits(
        base_path, edited_path,
        video_processor.preset_edits({
            "fps": fps,
            "trim_start": trim_start,
            "trim_end": trim_end,
        }),
    )

    # Step 3: get video duration
    config.log("  step 3: getting video duration...")
    info = video_processor.get_video_info(edited_path)
    duration = video_processor.get_duration(info)

    # Step 4: mix non-copyright BGM under the vocals
    final_path = edited_path
    config.log("  step 4: adding non-copyright BGM...")
    if audio_separator.has_audio(edited_path):
        bgm_source = (settings.get("bgm_source") or "yt_link").strip().lower()
        bgm_path = bgm_manager.resolve_bgm(bgm_source, duration, settings)
        if bgm_path:
            config.log(f"  BGM track: {Path(bgm_path).name}")
            trimmed = bgm_manager.trim_bgm(bgm_path, duration,
                                           output_dir / "trimmed_bgm.wav")
            final_path = output_dir / f"final_{input_path.name}"
            try:
                vocal_vol = float(settings.get("vocal_volume", 0.85))
            except (TypeError, ValueError):
                vocal_vol = 0.85
            try:
                bgm_vol = float(settings.get("bgm_volume", 0.20))
            except (TypeError, ValueError):
                bgm_vol = 0.20
            audio_separator.mix_audio(
                edited_path, trimmed, final_path,
                original_vol=vocal_vol, bgm_vol=bgm_vol
            )
        else:
            config.log("  no copyright-free BGM available — keeping vocals-only audio")
    else:
        config.log("  no audio to mix — keeping edited video")

    config.log(f"  done: {final_path.name}")
    return str(final_path)


def _format_template(tmpl, **kw):
    try:
        return tmpl.format(**kw)
    except (KeyError, IndexError, ValueError):
        return tmpl


# Sentinel for an explicit "download link in the comment" choice. The actual
# link is only known after the upload (shortening), so the marker survives the
# resolution step and is expanded at comment-posting time.
DOWNLOAD_LINK_COMMENT = "\x1fDOWNLOAD_LINK_COMMENT\x1f"
# Sentinel for an explicit "post no comment" choice. Needed to distinguish
# "not provided" (fall back to the configured custom comment) from a real
# skip (the user said no comment even though one is configured).
SKIP_COMMENT = "\x1fSKIP_COMMENT\x1f"


def resolve_fields(details, settings, *, title=None, description=None,
                   comment=None, url="", prefix=None, suffix=None, raw=False):
    """The single, authoritative title/description/comment resolution used by
    every upload path (quick deploy, instant, bulk, batch, CLI).

    Rules (applied in this order):
      - custom_title / custom_description empty  → the SOURCE video's own
        values are used automatically (never blank, never a placeholder).
      - `raw=True`                              → the provided title/description
        are used exactly as given (interactive flows); `raw=False` applies the
        project's configured fields (project flows).
      - `mirror_title_prefix` prepends to the title only when no custom title
        exists (project flows only); `mirror_description_suffix` is appended
        to the description the same way.
      - `comment`:
          * SKIP_COMMENT            → no comment (explicit user choice)
          * DOWNLOAD_LINK_COMMENT   → download-link comment (expanded later)
          * any other text          → used as-is (may contain {url}/{title})
          * None / empty            → configured custom comment, or if that is
                                      empty too → NO comment (never auto-posted)
      - Template tokens ({title}, {url}) that fail to expand are left intact
        rather than crashing the upload.

    Returns (title, description, comment) where `comment` is the final raw
    text, a sentinel, or None (= skipped)."""
    source_title = str((details or {}).get("title") or "")
    source_desc = str((details or {}).get("description") or "")
    settings = settings or {}
    if prefix is None:
        prefix = settings.get("mirror_title_prefix") or ""
    if suffix is None:
        suffix = settings.get("mirror_description_suffix") or ""
    custom_title = (settings.get("custom_title") or "").strip()
    custom_desc = (settings.get("custom_description") or "").strip()

    if raw:
        final_title = str(title or source_title or "")
        final_desc = str(description or source_desc or "")
    else:
        base = str(title or source_title or "")
        if custom_title:
            final_title = _format_template(custom_title, title=base, url=url)
        else:
            final_title = f"{prefix}{base}"
        if custom_desc:
            final_desc = _format_template(custom_desc, title=final_title, url=url)
        else:
            final_desc = str(description or source_desc or "")
        if suffix:
            final_desc = (final_desc + "\n" + suffix).strip()

    if comment == SKIP_COMMENT:
        final_comment = None
    elif comment == DOWNLOAD_LINK_COMMENT:
        final_comment = DOWNLOAD_LINK_COMMENT
    elif comment and str(comment).strip():
        final_comment = str(comment).strip()
    else:
        custom_comment = (settings.get("custom_comment") or "").strip()
        final_comment = custom_comment if custom_comment else None
    return final_title, final_desc, final_comment


def upload_daily(video_path, title=None, description=None,
                 tags=None, category_id="22", source_url=None, force=False,
                 source_channel="", comment=None, raw=False,
                 privacy_status=None, publish_at=None, details=None):
    youtube = youtube_api.get_client()

    settings = config.load_tui_settings()

    video_url = source_url or ""
    short_url = None
    if video_url:
        short_url = shortener.shorten_url(video_url)
        config.log(f"shortened: {video_url} → {short_url}")

    # Single source of truth for title/description/comment resolution
    title, description, comment = resolve_fields(
        details, settings,
        title=title, description=description, comment=comment,
        url=short_url or video_url, raw=raw)

    if not title:
        title = f"Daily Upload {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"

    thumbnail_path = None
    if source_url:
        m = re.search(r'(?:v=|youtu\.be/)([\w-]{11})', source_url)
        if m:
            vid = m.group(1)
            thumbnail_path = download_helpers.process_thumbnail(vid)

    config.log(f"uploading: {title}")

    upload_desc = description or ""
    video_id = youtube_api.upload_video(
        youtube, video_path,
        title=title,
        description=upload_desc,
        tags=tags or [],
        category_id=category_id,
        privacy_status=privacy_status or "public",
        thumbnail_path=thumbnail_path,
        publish_at=publish_at,
    )

    if video_id:
        comment_text = None
        if comment == DOWNLOAD_LINK_COMMENT:
            comment_text = f"Download link: {short_url or video_url}"
        elif comment:
            comment_text = _format_template(comment,
                                            url=short_url or video_url, title=title)
        else:
            config.log("comment skipped — no comment configured for this upload")

        comment_id = None
        if comment_text:
            if publish_at:
                # Scheduled uploads are private until YouTube auto-publishes
                # them, and the API refuses comments on private videos
                # (403 forbidden). Queue the comment — drain_pending_comments
                # posts it once the video is public.
                try:
                    supabase_db.add_pending_comment(
                        video_id, comment_text, project_id=config.PROJECT_ID,
                        publish_at=publish_at)
                    config.log(f"comment queued — posts when the video publishes ({publish_at})")
                except Exception as e:
                    config.log(f"comment queue failed (upload unaffected): {e}")
            else:
                try:
                    held = settings.get("comment_moderation", "published") == "heldForReview"
                    comment_id = youtube_api.post_comment(youtube, video_id, comment_text, held_for_review=held)
                    config.log(f"comment posted: {comment_id}")
                except Exception as e:
                    config.log(f"comment failed (upload unaffected): {e}")

        state = load_upload_state()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state["last_upload_date"] = today
        state["last_upload_hour"] = datetime.now(timezone.utc).isoformat()
        state["total_uploaded"] = state.get("total_uploaded", 0) + 1
        # Mark the SOURCE video as processed only after a successful upload
        source_vid = ""
        if video_url:
            m = re.search(r'(?:v=|youtu\.be/)([\w-]{11})', video_url)
            if m:
                source_vid = m.group(1)
                processed = state.get("processed_hashes", [])
                if source_vid not in processed:
                    processed.append(source_vid)
                    state["processed_hashes"] = processed
        save_upload_state(state)

        entry = {
            "upload_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "upload_time": datetime.now(timezone.utc).isoformat(),
            "video_id": video_id,
            "title": title,
            "short_url": short_url or "",
            "comment_id": comment_id or "",
            "source_video_id": source_vid,
            "source_channel": source_channel or "",
            "account_name": "",
        }
        if supabase_db.is_enabled():
            supabase_db.add_upload_log(entry, project_id=config.PROJECT_ID)
            try:
                account = supabase_db.get_project_account(config.PROJECT_ID)
                if account:
                    supabase_db.increment_account_uploads(account["name"])
            except Exception as e:
                config.log(f"account upload count update failed: {e}")
        else:
            log = load_daily_log()
            log["uploads"].append(entry)
            if len(log["uploads"]) > 100:
                log["uploads"] = log["uploads"][-100:]
            save_daily_log(log)

        config.log(f"uploaded: {video_id}")

    return video_id


# ─── Queued comments for scheduled uploads ────────────────────────────────
# Scheduled uploads go up private (publishAt) and the YouTube API refuses
# comments on private videos, so upload_daily queues the comment instead.
# drain_pending_comments posts each one once the video is public (publish_at
# passed). Runs on TUI startup and `yt-auto comments`.

def _http_error_reason(e):
    try:
        err = json.loads(e.content.decode("utf-8"))
        return err["error"]["errors"][0]["reason"]
    except Exception:
        return ""


def _comment_client(entry):
    """YouTube client for a queued comment: the project's embedded creds
    first, then its linked account. None when no credentials exist (the
    project/account was deleted)."""
    cid = csec = rtoken = ""
    pid = str(entry.get("project_id") or "")
    try:
        project = supabase_db.get_project(pid) if pid else None
    except Exception:
        project = None
    if project:
        cid = project.get("yt_client_id") or ""
        csec = project.get("yt_client_secret") or ""
        rtoken = project.get("yt_refresh_token") or ""
    if not rtoken and pid:
        try:
            acct = supabase_db.get_project_account(pid)
        except Exception:
            acct = None
        if acct:
            cid = acct.get("client_id") or cid
            csec = acct.get("client_secret") or csec
            rtoken = acct.get("refresh_token") or ""
    if not cid or not rtoken:
        return None
    try:
        return youtube_api.get_client(cid, csec, rtoken)
    except Exception:
        return None


def drain_pending_comments():
    """Post queued comments whose videos have published. Returns (posted,
    dropped). Never raises — every failure either retries later or drops
    the entry with a log line."""
    posted, dropped = 0, 0
    now = datetime.now(timezone.utc)
    for entry in supabase_db.list_pending_comments():
        try:
            due = datetime.fromisoformat(entry["publish_at"].replace("Z", "+00:00"))
        except (TypeError, ValueError, KeyError):
            due = now
        if due > now:
            continue
        yt = _comment_client(entry)
        if yt is None:
            supabase_db.remove_pending_comment(entry["id"])
            dropped += 1
            config.log(f"queued comment dropped (no credentials left): {entry['video_id']}")
            continue
        try:
            youtube_api.post_comment(yt, entry["video_id"], entry["comment"])
            supabase_db.remove_pending_comment(entry["id"])
            posted += 1
            config.log(f"queued comment posted on {entry['video_id']}")
        except Exception as e:
            reason = _http_error_reason(e)
            if reason == "commentsDisabled":
                supabase_db.remove_pending_comment(entry["id"])
                dropped += 1
                config.log(f"queued comment dropped (comments disabled): {entry['video_id']}")
            elif reason in ("forbidden", "insufficientPermissions"):
                attempts = int(entry.get("attempts") or 0) + 1
                if attempts >= 5:
                    supabase_db.remove_pending_comment(entry["id"])
                    dropped += 1
                    config.log(f"queued comment dropped after 5 attempts "
                               f"(video still not commentable): {entry['video_id']}")
                else:
                    supabase_db.increment_pending_attempt(entry["id"])
            else:
                supabase_db.increment_pending_attempt(entry["id"])
    return posted, dropped


def get_status():
    state = load_upload_state()
    return {
        "total_uploaded": state.get("total_uploaded", 0),
        "last_upload": state.get("last_upload_date"),
        "processed_count": len(state.get("processed_hashes", [])),
    }
