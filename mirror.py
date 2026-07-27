import os
import sys
import time
import tempfile
import shutil

import config
import youtube_api
import monitor
import download_helpers
import shortener


def mirror_video(youtube, video, cfg, my_channel_id, my_channel_title):
    vid = video["video_id"]
    state = config.load_state()
    processed = state.get("processed", {})
    source = video.get("source_channel_id", "")

    mirror_key = f"{source}:{vid}"
    if mirror_key in processed:
        config.log(f"already mirrored: {vid}")
        return None

    config.log(f"mirroring: [{video.get('channel_title', '?')}] {video['title'][:60]}")

    import re
    prefix = cfg.get("mirror_title_prefix", "")
    suffix = cfg.get("mirror_description_suffix", "")
    new_title = f"{prefix}{video['title']}{suffix}".strip()

    # Extract URLs from description
    orig_desc = video.get("description", "").rstrip()
    url_pattern = re.compile(r'https?://[^\s<>"\')\]]+')
    found_urls = url_pattern.findall(orig_desc)
    # Filter out YouTube URLs (we handle the video link separately)
    desc_urls = [u for u in found_urls if "youtube.com/watch" not in u and "youtu.be/" not in u]

    # Shorten all URLs: video + description links
    download_url = f"https://www.youtube.com/watch?v={vid}"
    all_short = {}
    all_short["video"] = shortener.shorten_url(download_url)
    for i, url in enumerate(desc_urls):
        key = f"desc_{i}"
        all_short[key] = shortener.shorten_url(url)
        time.sleep(0.5)  # rate limit shortener
    total_short = sum(1 for k, v in all_short.items() if k != "video" and v != desc_urls[int(k.split("_")[1])])
    state["stats"]["total_shortened"] = state["stats"].get("total_shortened", 0) + total_short + (1 if all_short["video"] != download_url else 0)

    # Build comment with numbered links
    comment_lines = []
    link_num = 1
    comment_lines.append("Download link in pinned comment 👇")
    comment_lines.append("")
    comment_lines.append(f"Download link: {all_short['video']}")
    if desc_urls:
        comment_lines.append("")
        comment_lines.append("Links from original description:")
        for i, url in enumerate(desc_urls):
            short = all_short.get(f"desc_{i}", url)
            comment_lines.append(f"  [{link_num}] {short}")
            link_num += 1
    comment_text = "\n".join(comment_lines)

    # Build description: keep original as-is + credit at bottom
    description_lines = []
    if orig_desc:
        description_lines.append(orig_desc)
        description_lines.append("")
    description_lines.append("---")
    description_lines.append(f"Channel: {video.get('channel_title', '')}")
    description_lines.append(f"Original: https://www.youtube.com/watch?v={vid}")
    if suffix:
        description_lines.append("")
        description_lines.append(suffix)
    new_description = "\n".join(description_lines)

    tags = video.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    tags.extend(["mirror", video.get("channel_title", ""), "reupload"])
    tags = list(dict.fromkeys(tags))[:30]

    thumbnail_path = None
    thumb_url = video.get("thumbnail", "")
    if thumb_url:
        thumbnail_path = os.path.join(tempfile.mkdtemp(), "thumb.jpg")
        download_helpers.download_thumbnail(thumb_url, thumbnail_path)

    video_path = None
    yt_url = f"https://www.youtube.com/watch?v={vid}"
    config.log(f"downloading video: {yt_url}")
    dl_result = download_helpers.download_video(yt_url)
    if dl_result:
        video_path = dl_result["path"]
    else:
        config.log("video download failed — skipping mirror")
        if thumbnail_path:
            shutil.rmtree(os.path.dirname(thumbnail_path), ignore_errors=True)
        return None

    file_size = os.path.getsize(video_path)
    config.log(f"video size: {file_size / (1024*1024):.1f}MB")

    if cfg.get("dry_run"):
        config.log(f"DRY RUN — would upload: {new_title}")
        config.log(f"  description: {new_description[:100]}...")
        config.log(f"  comment: {comment_text}")
        config.log(f"  thumbnail: {thumbnail_path}")
        _cleanup(video_path, thumbnail_path)
        return {"video_id": "dry_run", "title": new_title}

    try:
        new_video_id = youtube_api.upload_video(
            youtube, video_path, new_title, new_description,
            tags=tags,
            category_id=cfg.get("category_id", "22"),
            privacy_status=cfg.get("privacy_status", "public"),
            thumbnail_path=thumbnail_path,
        )
    except Exception as e:
        config.log(f"upload failed: {e}")
        _cleanup(video_path, thumbnail_path)
        return None

    state["stats"]["total_mirrored"] = state["stats"].get("total_mirrored", 0) + 1

    try:
        held = config.load_tui_settings().get("comment_moderation", "heldForReview") == "heldForReview"
        comment_id = youtube_api.post_comment(youtube, new_video_id, comment_text, held_for_review=held)
        state["stats"]["total_comments"] = state["stats"].get("total_comments", 0) + 1
        config.log(f"comment posted and pinned: {comment_id}")
    except Exception as e:
        config.log(f"comment failed: {e}")
        comment_id = None

    processed[mirror_key] = {
        "new_video_id": new_video_id,
        "original_title": video["title"],
        "mirrored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "comment_id": comment_id,
        "shortened_urls": all_short,
    }
    state["processed"] = processed
    config.save_state(state)

    _cleanup(video_path, thumbnail_path)
    return {"video_id": new_video_id, "title": new_title, "comment_id": comment_id}


def _cleanup(video_path, thumbnail_path):
    if video_path:
        try:
            os.unlink(video_path)
        except Exception:
            pass
        try:
            parent = os.path.dirname(video_path)
            if parent and os.path.isdir(parent):
                shutil.rmtree(parent, ignore_errors=True)
        except Exception:
            pass
    if thumbnail_path:
        try:
            shutil.rmtree(os.path.dirname(thumbnail_path), ignore_errors=True)
        except Exception:
            pass


def run_mirror_cycle():
    config.set_start_time(time.time())
    config.log("=== Mirror cycle started ===")

    if not config.is_configured():
        config.log("YouTube credentials not configured — exiting")
        return {"mirrored": 0, "comments": 0, "errors": ["not configured"]}

    account_name = config.get_active_account_name()
    if account_name:
        config.log(f"active account: {account_name}")

    try:
        youtube = youtube_api.get_client()
        my_id, my_title = youtube_api.get_my_channel_id(youtube)
        config.log(f"authenticated as: @{my_title} ({my_id})")
    except Exception as e:
        config.log(f"authentication failed: {e}")
        return {"mirrored": 0, "comments": 0, "errors": [str(e)]}

    cfg = config.load()
    state = config.load_state()

    new_videos = monitor.check_all_channels(youtube, state)
    config.save_state(state)

    if not new_videos:
        config.log("no new videos to mirror")
        return {"mirrored": 0, "comments": 0, "errors": []}

    mirrored = 0
    comments = 0
    errors = []

    for v in new_videos[:cfg.get("max_per_cycle", 3)]:
        try:
            result = mirror_video(youtube, v, cfg, my_id, my_title)
            if result:
                mirrored += 1
                if result.get("comment_id"):
                    comments += 1
        except Exception as e:
            config.log(f"mirror error for {v['video_id']}: {e}")
            errors.append(f"{v['video_id']}: {str(e)[:80]}")
        time.sleep(2)

    config.log(f"=== cycle done: {mirrored} mirrored, {comments} comments, {len(errors)} errors ===")

    final_state = config.load_state()
    stats = final_state.get("stats", {})
    config.log(f"total stats: {stats.get('total_mirrored', 0)} mirrored, {stats.get('total_comments', 0)} comments, {stats.get('total_shortened', 0)} shortened")

    return {"mirrored": mirrored, "comments": comments, "errors": errors}


if __name__ == "__main__":
    result = run_mirror_cycle()
    if result.get("errors") and not result.get("mirrored"):
        sys.exit(1)
