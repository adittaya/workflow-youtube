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


def process_video(input_path, output_dir=None):
    # Every video is processed from scratch in its own scratch dir so the
    # next video never reuses the previous one's artifacts. The caller is
    # responsible for dedup (processed_hashes holds source video IDs, added
    # only AFTER a successful upload) — never mark a video processed here.
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

    fps = _int_setting("fps", 20)
    trim_start = _int_setting("trim_start", 20)
    trim_end = _int_setting("trim_end", 10)
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
    duration = float(info.get("format", {}).get("duration", 60))

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


def _extract_keywords(description):
    """Pull only the keyword/tag block out of a copied description: hashtags
    found anywhere plus the trailing run of keyword-like lines at the bottom.
    Returns '' when nothing keyword-ish exists."""
    if not description:
        return ""
    lines = str(description).splitlines()

    hashtags = []
    for line in lines:
        for tok in re.findall(r"#[A-Za-z0-9_]+", line):
            if tok not in hashtags:
                hashtags.append(tok)

    def _keyword_line(s):
        if s.startswith("#"):
            return True
        if re.search(r"https?://", s):
            return False
        if any(c in s for c in ".!?;"):
            return False
        tokens = [t for t in re.split(r"[,/\\\s]+", s) if t]
        if not tokens:
            return False
        return all(len(t) <= 40 for t in tokens)

    trailing = []
    for line in reversed(lines):
        s = line.strip()
        if not s:
            if trailing:
                break
            continue
        if _keyword_line(s):
            trailing.insert(0, s)
        else:
            break

    parts = list(hashtags)
    for line in trailing:
        if line not in parts:
            parts.append(line)
    return "\n".join(parts)


def upload_daily(video_path, title=None, description=None,
                 tags=None, category_id="22", source_url=None, force=False,
                 source_channel="", comment=None, raw=False,
                 privacy_status=None):
    youtube = youtube_api.get_client()

    settings = config.load_tui_settings()
    prefix = settings.get("mirror_title_prefix", "")
    suffix = settings.get("mirror_description_suffix", "")

    if title is None:
        title = f"Daily Upload {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"

    video_url = source_url or ""
    short_url = None
    if video_url:
        short_url = shortener.shorten_url(video_url)
        config.log(f"shortened: {video_url} → {short_url}")

    custom_title = (settings.get("custom_title") or "").strip()
    if custom_title and not raw:
        title = _format_template(custom_title, title=title, url=short_url or video_url)
    elif not raw:
        title = f"{prefix}{title}{suffix}"

    thumbnail_path = None
    if source_url:
        m = re.search(r'(?:v=|youtu\.be/)([\w-]{11})', source_url)
        if m:
            vid = m.group(1)
            thumbnail_path = download_helpers.process_thumbnail(vid)

    config.log(f"uploading: {title}")

    custom_desc = (settings.get("custom_description") or "").strip()
    if custom_desc and (description is None or not raw):
        upload_desc = _format_template(custom_desc, title=title, url=short_url or video_url)
    elif raw and description:
        upload_desc = description
    else:
        upload_desc = "Download link in pinned comment"
        keywords = _extract_keywords(description) if description else ""
        if keywords:
            upload_desc += "\n\n" + keywords

    video_id = youtube_api.upload_video(
        youtube, video_path,
        title=title,
        description=upload_desc,
        tags=tags or [],
        category_id=category_id,
        privacy_status=privacy_status or "public",
        thumbnail_path=thumbnail_path,
    )

    if video_id:
        comment_text = None
        if comment:
            comment_text = comment
        else:
            custom_comment = (settings.get("custom_comment") or "").strip()
            if custom_comment:
                comment_text = _format_template(custom_comment,
                                                url=short_url or video_url, title=title)
            elif short_url:
                comment_text = f"Download link: {short_url}"
            elif video_url:
                comment_text = f"Download link: {video_url}"

        comment_id = None
        if comment_text:
            try:
                held = settings.get("comment_moderation", "published") == "heldForReview"
                comment_id = youtube_api.post_comment(youtube, video_id, comment_text, held_for_review=held)
                config.log(f"comment posted: {comment_id}")
            except Exception as e:
                config.log(f"comment failed: {e}")

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


def get_status():
    state = load_upload_state()
    return {
        "total_uploaded": state.get("total_uploaded", 0),
        "last_upload": state.get("last_upload_date"),
        "processed_count": len(state.get("processed_hashes", [])),
    }
