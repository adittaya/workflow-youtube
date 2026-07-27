import config
import youtube_api


def _resolve_channel_id(youtube, channel_id):
    if channel_id.startswith("UC") and len(channel_id) > 20:
        return channel_id
    if channel_id.startswith("@"):
        resp = youtube.channels().list(part="id", forHandle=channel_id).execute()
        items = resp.get("items", [])
        if items:
            return items[0]["id"]
    return channel_id


def check_channel(youtube, channel_id, state):
    processed = state.get("processed", {})
    resolved = _resolve_channel_id(youtube, channel_id)
    channel_key = channel_id
    if channel_key not in processed:
        processed[channel_key] = {"last_video_id": ""}

    playlist_id = youtube_api.get_channel_uploads_playlist(youtube, resolved)
    if not playlist_id:
        config.log(f"no uploads playlist for {channel_id}")
        return []

    videos = youtube_api.get_recent_videos(youtube, playlist_id, max_results=10)
    if not videos:
        config.log(f"no videos found for {channel_id}")
        return []

    last_known = processed[channel_key].get("last_video_id", "")
    new_videos = []

    if not last_known:
        processed[channel_key]["last_video_id"] = videos[0]["video_id"]
        config.log(f"first check for {channel_id} — recording {videos[0]['video_id']} as latest")
        return []

    for v in videos:
        if v["video_id"] == last_known:
            break
        new_videos.append(v)

    if new_videos:
        processed[channel_key]["last_video_id"] = new_videos[0]["video_id"]
        config.log(f"found {len(new_videos)} new video(s) from {channel_id}")
    else:
        config.log(f"no new videos from {channel_id}")

    return new_videos


def check_all_channels(youtube, state):
    channels = config.load_channels()
    all_new = []
    for cid, info in channels.items():
        if not info.get("enabled", True):
            continue
        new_vids = check_channel(youtube, cid, state)
        for v in new_vids:
            v["source_channel_id"] = cid
            v["source_channel_alias"] = info.get("alias", cid)
        all_new.extend(new_vids)
    return all_new
