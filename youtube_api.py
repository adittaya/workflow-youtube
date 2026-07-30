import os
import time

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

import config

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube",
]

MAX_RETRIES = 3
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]
UPLOAD_CHUNK_SIZE = 1024 * 1024 * 10


def get_client():
    creds_data = config.get_yt_credentials()
    if not all(creds_data.values()):
        raise RuntimeError("YouTube credentials not configured — set YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN")
    creds = Credentials(
        token=None,
        refresh_token=creds_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def get_my_channel_id(youtube):
    resp = youtube.channels().list(part="id,snippet", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise RuntimeError("No channel found for this credentials — check OAuth scopes")
    return items[0]["id"], items[0]["snippet"]["title"]


def get_channel_uploads_playlist(youtube, channel_id):
    if channel_id.startswith("@"):
        resp = youtube.channels().list(part="contentDetails", forHandle=channel_id[1:]).execute()
    else:
        resp = youtube.channels().list(part="contentDetails", id=channel_id).execute()
    items = resp.get("items", [])
    if not items:
        return None
    return items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")


def get_recent_videos(youtube, playlist_id, max_results=10):
    resp = youtube.playlistItems().list(
        part="snippet,contentDetails",
        playlistId=playlist_id,
        maxResults=max_results,
    ).execute()
    videos = []
    for item in resp.get("items", []):
        vid = item["contentDetails"]["videoId"]
        snippet = item["snippet"]
        videos.append({
            "video_id": vid,
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", "")
                         or snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
            "published_at": snippet.get("publishedAt", ""),
            "channel_id": snippet.get("channelId", ""),
            "channel_title": snippet.get("channelTitle", ""),
        })
    return videos


def _parse_duration_iso8601(duration):
    import re
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not m:
        return 0
    h = int(m.group(1)) if m.group(1) else 0
    m_min = int(m.group(2)) if m.group(2) else 0
    s = int(m.group(3)) if m.group(3) else 0
    return h * 3600 + m_min * 60 + s


def filter_long_form_videos(youtube, videos):
    if not videos:
        return videos
    ids = [v['video_id'] for v in videos]
    try:
        resp = youtube.videos().list(part="contentDetails", id=",".join(ids)).execute()
        duration_map = {}
        for item in resp.get("items", []):
            vid = item["id"]
            dur_str = item.get("contentDetails", {}).get("duration", "PT0S")
            duration_map[vid] = _parse_duration_iso8601(dur_str)
        long_form = []
        for v in videos:
            vid = v['video_id']
            dur = duration_map.get(vid, 0)
            if dur >= 60:
                long_form.append(v)
            else:
                config.log(f"skipping short video: {vid} ({dur}s)")
        return long_form
    except Exception as e:
        config.log(f"video details fetch failed: {e}")
        return videos


def get_video_details(youtube, video_id):
    resp = youtube.videos().list(part="snippet,contentDetails", id=video_id).execute()
    items = resp.get("items", [])
    if not items:
        return None
    item = items[0]
    snippet = item.get("snippet", {})
    dur_str = item.get("contentDetails", {}).get("duration", "PT0S")
    return {
        "video_id": video_id,
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "tags": snippet.get("tags", []),
        "channel_title": snippet.get("channelTitle", ""),
        "duration": _parse_duration_iso8601(dur_str),
        "thumbnail": snippet.get("thumbnails", {}).get("maxres", {}).get("url", "")
                      or snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
    }


def upload_video(youtube, file_path, title, description, tags=None, category_id="22",
                 privacy_status="public", thumbnail_path=None, progress_callback=None,
                 publish_at=None):
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {
            "selfDeclaredMadeForKids": False,
        },
    }
    if publish_at:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = publish_at
    else:
        body["status"]["privacyStatus"] = privacy_status
    parts = "snippet,status"
    media = MediaFileUpload(file_path, chunksize=UPLOAD_CHUNK_SIZE, resumable=True, mimetype="video/*")
    request = youtube.videos().insert(part=parts, body=body, media_body=media)

    response = None
    retry = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status and progress_callback:
                progress_callback(int(status.progress() * 100))
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES:
                retry += 1
                if retry > MAX_RETRIES:
                    raise
                time.sleep(2 ** retry)
            else:
                raise

    video_id = response["id"]
    config.log(f"uploaded video: {video_id}")

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
            ).execute()
            config.log(f"thumbnail set for: {video_id}")
        except HttpError as e:
            config.log(f"thumbnail upload failed: {e}")

    return video_id


def update_video_description(youtube, video_id, description):
    resp = youtube.videos().list(part="snippet", id=video_id).execute()
    items = resp.get("items", [])
    if not items:
        return False
    snippet = items[0]["snippet"]
    snippet["description"] = description
    youtube.videos().update(part="snippet", body={
        "id": video_id,
        "snippet": {
            "title": snippet["title"],
            "description": description,
            "tags": snippet.get("tags", []),
            "categoryId": snippet.get("categoryId", "22"),
        },
    }).execute()
    return True


def post_comment(youtube, video_id, text, held_for_review=True):
    body = {
        "snippet": {
            "videoId": video_id,
            "topLevelComment": {
                "snippet": {
                    "textOriginal": text,
                }
            },
        }
    }
    resp = youtube.commentThreads().insert(part="snippet", body=body).execute()
    comment_id = resp["id"]

    if held_for_review:
        try:
            youtube.comments().update(
                part="snippet",
                body={
                    "id": comment_id,
                    "snippet": {
                        "textOriginal": text,
                        "moderationStatus": "heldForReview",
                    },
                },
            ).execute()
        except HttpError:
            pass

    config.log(f"comment posted: {comment_id} on {video_id}")
    return comment_id


def delete_video(youtube, video_id):
    try:
        youtube.videos().delete(id=video_id).execute()
        config.log(f"deleted video: {video_id}")
        return True
    except HttpError as e:
        config.log(f"delete failed for {video_id}: {e}")
        return False
