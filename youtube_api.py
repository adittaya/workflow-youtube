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


def _proxy_http():
    """Return an httplib2.Http routed through the configured proxy, or None."""
    proxy_url = config.get_proxy_url()
    if not proxy_url:
        return None
    import httplib2
    http = httplib2.Http(
        timeout=60,
        proxy_info=httplib2.proxy_info_from_url(proxy_url, "https"),
    )
    http.follow_redirects = False
    return http


def _plain_http():
    """Return a plain httplib2.Http with redirects disabled.

    Redirects are disabled because httplib2 treats the resumable upload
    protocol's 308 Resume Incomplete as a redirect code and raises
    ``RedirectMissingLocation`` when the response has no Location header
    (YouTube's 308 between chunks has none). googleapiclient's
    ``_process_response`` handles 308 itself, so httplib2 must not.
    """
    import httplib2
    http = httplib2.Http(timeout=60)
    http.follow_redirects = False
    return http


def get_client(client_id=None, client_secret=None, refresh_token=None):
    try:
        import proxy_pool
        proxy_pool.ensure_working()
    except Exception:
        pass
    config.apply_proxy_env()
    if client_id or client_secret or refresh_token:
        creds_data = {
            "client_id": client_id or "",
            "client_secret": client_secret or "",
            "refresh_token": refresh_token or "",
        }
    else:
        creds_data = config.get_yt_credentials()
    creds_data["client_id"] = config.sanitize_client_id(creds_data.get("client_id", ""))
    if not all(creds_data.values()):
        raise RuntimeError("YouTube credentials not configured — set YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN")
    creds = Credentials(
        token=None,
        refresh_token=creds_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
    )
    http = _proxy_http() or _plain_http()
    from google_auth_httplib2 import AuthorizedHttp
    return build("youtube", "v3", http=AuthorizedHttp(creds, http=http), cache_discovery=False)


def _parse_duration_iso8601(duration):
    import re
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    if not m:
        return 0
    h = int(m.group(1)) if m.group(1) else 0
    m_min = int(m.group(2)) if m.group(2) else 0
    s = int(m.group(3)) if m.group(3) else 0
    return h * 3600 + m_min * 60 + s


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
        "channel_id": snippet.get("channelId", ""),
        "duration": _parse_duration_iso8601(dur_str),
        "thumbnail": snippet.get("thumbnails", {}).get("maxres", {}).get("url", "")
                      or snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
    }


def upload_video(youtube, file_path, title, description, tags=None, category_id="22",
                 privacy_status="public", thumbnail_path=None, progress_callback=None):
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {
            "selfDeclaredMadeForKids": False,
            "privacyStatus": privacy_status,
        },
    }
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
