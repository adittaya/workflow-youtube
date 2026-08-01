import os
import subprocess
import json
import tempfile
import re
import config
from PIL import Image, ImageEnhance


def process_thumbnail(video_id, output_path=None):
    if output_path is None:
        output_path = os.path.join(tempfile.mkdtemp(), f"{video_id}_thumb.jpg")
    urls = [
        f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
    ]
    img = None
    for url in urls:
        try:
            import urllib.request
            req = urllib.request.urlopen(url, timeout=10)
            img = Image.open(req)
            break
        except Exception:
            continue
    if img is None:
        config.log(f"thumbnail download failed for: {video_id}")
        return None
    img = img.convert("RGB")
    img = ImageEnhance.Brightness(img).enhance(1.05)
    img = ImageEnhance.Color(img).enhance(1.05)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, "JPEG", quality=95)
    config.log(f"thumbnail processed: {output_path}")
    return output_path


def download_video(url, output_dir=None):
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="yt_mirror_")
    proxies_raw = os.environ.get("WORKING_PROXIES", "")
    proxies = json.loads(proxies_raw) if proxies_raw else []
    if not proxies:
        single = os.environ.get("YT_PROXY", "")
        if single:
            proxies = [single]

    for i, proxy in enumerate(proxies):
        config.log(f"yt-dlp attempt {i + 1}/{len(proxies)} with proxy: {proxy}")
        result = _try_download(url, output_dir, proxy)
        if result:
            return result
        config.log(f"proxy {i + 1} failed — trying next")
    if not proxies:
        config.log("no proxy configured — trying direct download")
        return _try_download(url, output_dir, "")
    return None


def _cookies_arg():
    """Resolve a cookies file for yt-dlp: prefer YT_COOKIES_FILE if it exists,
    otherwise materialize the YT_COOKIES secret text into
    ~/.yt-mirror/cookies.txt."""
    path = os.environ.get("YT_COOKIES_FILE", "")
    if path and os.path.exists(path):
        return path
    raw = os.environ.get("YT_COOKIES", "")
    if not raw:
        return None
    data_dir = os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror"))
    fallback = os.path.join(data_dir, "cookies.txt")
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(fallback, "w") as f:
            f.write(raw if raw.endswith("\n") else raw + "\n")
        os.chmod(fallback, 0o600)
        return fallback
    except Exception as e:
        config.log(f"cookies write failed: {e}")
        return None


def _try_download(url, output_dir, proxy):
    output_template = os.path.join(output_dir, "video.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--force-ipv4",
        "--extractor-args", "youtube:player_client=android;formats=duplicate,missing_pot",
        "-f", "best",
        "-o", output_template,
        "--print-json",
        url,
    ]
    if proxy:
        cmd.extend(["--proxy", proxy])
    cookies = _cookies_arg()
    if cookies:
        cmd.extend(["--cookies", cookies])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            config.log(f"yt-dlp failed: {result.stderr[:200]}")
            return None
        info = json.loads(result.stdout) if result.stdout.strip() else {}
        filepath = info.get("filename") or info.get("_filename")
        if filepath and os.path.exists(filepath):
            config.log(f"video downloaded: {filepath}")
            return {"path": filepath, "info": info}
        for f in os.listdir(output_dir):
            if f.startswith("video."):
                full = os.path.join(output_dir, f)
                config.log(f"video downloaded: {full}")
                return {"path": full, "info": info}
        config.log("yt-dlp finished but no video file found")
        return None
    except subprocess.TimeoutExpired:
        config.log("yt-dlp download timed out (300s)")
        return None
    except Exception as e:
        config.log(f"download error: {e}")
        return None
