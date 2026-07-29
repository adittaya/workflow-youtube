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
        "--force-ipv4",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        "--extractor-args", "youtube:player_client=mweb,web_safari;formats=duplicate,missing_pot",
        "-f", "best[protocol!=http_dash_segments]",
        "-o", output_template,
        "--print-json",
        url,
    ]
    cookies_file = os.environ.get("YT_COOKIES_FILE", "")
    if cookies_file and os.path.exists(cookies_file):
        cmd.append("--cookies")
        cmd.append(cookies_file)
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
