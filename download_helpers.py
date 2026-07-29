import os
import subprocess
import json
import tempfile
import config


def download_thumbnail(url, output_path):
    if not url:
        return False
    try:
        import urllib.request
        urllib.request.urlretrieve(url, output_path)
        config.log(f"thumbnail downloaded: {output_path}")
        return True
    except Exception as e:
        config.log(f"thumbnail download failed: {e}")
        return False


def download_video(url, output_dir=None):
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="yt_mirror_")
    output_template = os.path.join(output_dir, "video.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--js-runtimes", "node",
        "--extractor-args", "youtube:player_client=android",
        "--extractor-args", "youtube:skip=webpage,configs",
        "--user-agent",
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.122 Mobile Safari/537.36",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "--throttled-rate", "100K",
        "-o", output_template,
        "--print-json",
        url,
    ]
    cookies_file = os.environ.get("YT_COOKIES_FILE", "")
    if cookies_file:
        config.log(f"cookies file path: {cookies_file}, exists: {os.path.exists(cookies_file)}")
        if os.path.exists(cookies_file):
            size = os.path.getsize(cookies_file)
            config.log(f"cookies file size: {size}")
            cmd.append("--cookies")
            cmd.append(cookies_file)
        else:
            config.log("cookies file not found")
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
