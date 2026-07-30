import json
import os
import re
import time
import subprocess
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone

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
WARMUP_STATE = DATA_DIR / "warmup_state.json"
DAILY_LOG = DATA_DIR / "daily_log.json"

WARMUP_DAYS_DEFAULT = 0
MAX_VIDEOS_PER_DAY = 1
MIN_HOURS_BETWEEN = 18


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
            "warmup_start": None,
            "warmup_complete": False,
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


def start_warmup(force=False):
    state = load_upload_state()
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    if force or not state.get("warmup_start"):
        state["warmup_start"] = now.isoformat()
        state["account_created"] = state.get("account_created") or now.isoformat()
        state["warmup_complete"] = False
        save_upload_state(state)
        config.log(f"warmup started: {state['warmup_start']}")
    else:
        start = datetime.fromisoformat(state["warmup_start"])
        # Strip tz so we can subtract even if one is naive and other aware
        if start.tzinfo is not None:
            start = start.replace(tzinfo=None)
        naive_now = now.replace(tzinfo=None)
        days = (naive_now - start).days
        warmup_total = get_warmup_days()
        if days >= warmup_total and not state.get("warmup_complete"):
            state["warmup_complete"] = True
            save_upload_state(state)
            config.log(f"warmup complete: {days} days elapsed")

    return state


def reset_warmup(reason="account changed"):
    state = load_upload_state()
    state["warmup_start"] = datetime.now(timezone.utc).isoformat()
    state["warmup_complete"] = False
    state["total_uploaded"] = 0
    state["last_upload_date"] = None
    state["last_upload_hour"] = None
    state["processed_hashes"] = []
    save_upload_state(state)
    config.log(f"warmup reset: {reason}")
    return state


def get_warmup_days():
    try:
        settings = json.loads((DATA_DIR / "settings.json").read_text("utf-8"))
        return int(settings.get("warmup_days", WARMUP_DAYS_DEFAULT))
    except Exception:
        return WARMUP_DAYS_DEFAULT

_get_warmup_days = get_warmup_days


def get_warmup_day():
    state = load_upload_state()
    if not state.get("warmup_start"):
        return 0
    start = datetime.fromisoformat(state["warmup_start"])
    if start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    delta = datetime.now(timezone.utc).replace(tzinfo=None) - start
    return delta.days


def is_warmup_complete():
    state = load_upload_state()
    if state.get("warmup_complete"):
        return True
    return get_warmup_day() >= _get_warmup_days()


def can_upload_today():
    state = load_upload_state()

    if not is_warmup_complete():
        day = get_warmup_day()
        config.log(f"warmup day {day}/{_get_warmup_days()} - no uploads yet")
        return False, f"warmup day {day}/{_get_warmup_days()}"

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("last_upload_date") == today:
        log = load_daily_log()
        today_uploads = [u for u in log["uploads"]
                         if u.get("date") == today]
        if len(today_uploads) >= MAX_VIDEOS_PER_DAY:
            return False, f"already uploaded {MAX_VIDEOS_PER_DAY} today"

    if state.get("last_upload_hour"):
        last = datetime.fromisoformat(state["last_upload_hour"])
        if last.tzinfo is not None:
            last = last.replace(tzinfo=None)
        hours_since = (datetime.now(timezone.utc).replace(tzinfo=None) - last).total_seconds() / 3600
        if hours_since < MIN_HOURS_BETWEEN:
            wait = MIN_HOURS_BETWEEN - hours_since
            return False, f"wait {wait:.1f}h more"

    return True, "ready"


def process_video(input_path, output_dir=None):
    if output_dir is None:
        output_dir = DATA_DIR / "processed"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_path = Path(input_path)
    video_hash = video_processor.get_video_hash(input_path)

    state = load_upload_state()
    if video_hash in state.get("processed_hashes", []):
        config.log(f"video already processed: {input_path.name}")
        return None

    config.log(f"processing: {input_path.name}")

    config.log("  step 1: applying video edits...")
    edited_path = output_dir / f"edited_{input_path.name}"
    video_processor.apply_edits(input_path, edited_path)

    config.log("  step 2: getting video duration...")
    info = video_processor.get_video_info(edited_path)
    duration = float(info.get("format", {}).get("duration", 60))

    config.log("  step 3: adding non-copyright BGM...")
    bgm_path = bgm_manager.get_bgm_for_duration(duration)
    if bgm_path:
        trimmed = bgm_manager.trim_bgm(bgm_path, duration,
                                        output_dir / "trimmed_bgm.wav")
        final_path = output_dir / f"final_{input_path.name}"
        audio_separator.mix_audio(
            edited_path, trimmed, final_path,
            original_vol=1.0, bgm_vol=0.30
        )
    else:
        final_path = edited_path

    state["processed_hashes"] = state.get("processed_hashes", []) + [video_hash]
    if len(state["processed_hashes"]) > 200:
        state["processed_hashes"] = state["processed_hashes"][-200:]
    save_upload_state(state)

    config.log(f"  done: {final_path.name}")
    return str(final_path)


def upload_daily(video_path, title=None, description=None,
                 tags=None, category_id="22", source_url=None):
    can, reason = can_upload_today()
    if not can:
        config.log(f"cannot upload: {reason}")
        return None

    youtube = youtube_api.get_client()

    settings = config.load_tui_settings()
    prefix = settings.get("mirror_title_prefix", "")
    suffix = settings.get("mirror_description_suffix", "")

    if title is None:
        title = f"Daily Upload {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    title = f"{prefix}{title}{suffix}"

    video_url = source_url or ""
    short_url = None
    if video_url:
        short_url = shortener.shorten_url(video_url)
        config.log(f"shortened: {video_url} → {short_url}")

    thumbnail_path = None
    if source_url:
        m = re.search(r'(?:v=|youtu\.be/)([\w-]{11})', source_url)
        if m:
            vid = m.group(1)
            thumbnail_path = download_helpers.process_thumbnail(vid)

    config.log(f"uploading: {title}")

    upload_desc = "Download link in pinned comment\n\n"
    if description:
        upload_desc += description + "\n\n"
    if short_url or video_url:
        upload_desc += "Original: " + (short_url or video_url)

    video_id = youtube_api.upload_video(
        youtube, video_path,
        title=title,
        description=upload_desc,
        tags=tags or [],
        category_id=category_id,
        privacy_status="public",
        thumbnail_path=thumbnail_path,
    )

    if video_id:
        comment_text = None
        if short_url:
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
        state["last_upload_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state["last_upload_hour"] = datetime.now(timezone.utc).isoformat()
        state["total_uploaded"] = state.get("total_uploaded", 0) + 1
        save_upload_state(state)

        entry = {
            "upload_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "upload_time": datetime.now(timezone.utc).isoformat(),
            "video_id": video_id,
            "title": title,
            "short_url": short_url or "",
            "comment_id": comment_id or "",
        }
        if supabase_db.is_enabled():
            supabase_db.add_upload_log(entry, project_id=config.PROJECT_ID)
        else:
            log = load_daily_log()
            log["uploads"].append(entry)
            if len(log["uploads"]) > 100:
                log["uploads"] = log["uploads"][-100:]
            save_daily_log(log)

        config.log(f"uploaded: {video_id}")

    return video_id


def process_and_upload(input_path, title=None, description=None,
                        tags=None, source_url=None):
    can, reason = can_upload_today()
    if not can:
        return None, reason

    processed = process_video(input_path)
    if not processed:
        return None, "processing failed or duplicate"

    video_id = upload_daily(processed, title, description, tags, source_url=source_url)
    if video_id:
        return video_id, "uploaded"
    return None, "upload failed"


def get_status():
    state = load_upload_state()
    warmup_day = get_warmup_day()
    can, reason = can_upload_today()

    return {
        "warmup_day": warmup_day,
        "warmup_total": _get_warmup_days(),
        "warmup_complete": is_warmup_complete(),
        "can_upload": can,
        "upload_reason": reason,
        "total_uploaded": state.get("total_uploaded", 0),
        "last_upload": state.get("last_upload_date"),
        "processed_count": len(state.get("processed_hashes", [])),
    }
