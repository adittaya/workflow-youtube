import os
import subprocess
import json
import tempfile
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


def get_proxy_candidates():
    """Proxy candidates in priority order: configured proxy (Settings screen),
    then WORKING_PROXIES JSON, then a single YT_PROXY."""
    proxies = []
    url = config.get_proxy_url()
    if url:
        proxies.append(url)
    raw = os.environ.get("WORKING_PROXIES", "")
    if raw:
        for p in json.loads(raw):
            if p not in proxies:
                proxies.append(p)
    if not proxies:
        single = os.environ.get("YT_PROXY", "")
        if single:
            proxies = [single]
    return proxies


class YouTubeBotCheck(Exception):
    """YouTube returned a bot check ("Sign in to confirm you're not a bot").

    Raised by download_video() when every proxy attempt (including a direct
    connection) was blocked this way. It means the IP is flagged and requests
    are anonymous — fix by providing cookies or using a residential proxy.
    """


def download_video(url, output_dir=None):
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="yt_mirror_")
    try:
        import proxy_pool
        proxy_pool.ensure_working()
    except Exception:
        pass
    proxies = get_proxy_candidates()
    try:
        import proxy_pool
        for p in proxy_pool.candidate_urls():
            if p not in proxies:
                proxies.append(p)
    except Exception:
        pass
    saw_bot_check = False

    if not proxies:
        config.log("no proxy configured — trying direct download")
        result, kind = _try_download(url, output_dir, "")
        if result:
            return result
        if kind == "bot_check":
            saw_bot_check = True
    for i, proxy in enumerate(proxies):
        config.log(f"yt-dlp attempt {i + 1}/{len(proxies)} with proxy: {proxy}")
        result, kind = _try_download(url, output_dir, proxy)
        if result:
            return result
        if kind == "bot_check":
            saw_bot_check = True
            try:
                import proxy_pool
                proxy_pool.mark_blocked(proxy)
                config.log(f"parking flagged proxy: {proxy}")
            except Exception:
                pass
        config.log(f"proxy {i + 1} failed — trying next")
    if saw_bot_check:
        raise YouTubeBotCheck(
            f"YouTube blocked all {len(proxies) or 1} proxy attempt(s) with "
            "'Sign in to confirm you're not a bot'. The proxy IPs are flagged "
            "and requests are anonymous. Set YT_COOKIES_FILE / YT_COOKIES "
            "(cookies.txt from a logged-in browser) or use residential proxies.")
    return None


def tools_ok():
    """True when yt-dlp is present on PATH."""
    import shutil
    return shutil.which("yt-dlp") is not None


def _cookies_arg():
    """Resolve a cookies file for yt-dlp: prefer YT_COOKIES_FILE if it exists,
    then a configured `cookies_file` setting, otherwise materialize the
    YT_COOKIES secret text into ~/.yt-mirror/cookies.txt."""
    path = os.environ.get("YT_COOKIES_FILE", "")
    if not path:
        path = str(config.get_setting("cookies_file", "") or "")
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


def _cookies_browser_arg():
    """Browser name for --cookies-from-browser (YT_COOKIES_BROWSER env or a
    `cookies_browser` setting). Only used when no cookies file is available."""
    return (os.environ.get("YT_COOKIES_BROWSER", "")
            or str(config.get_setting("cookies_browser", "") or "")).strip() or None


def run_yt_dlp(args, proxy="", timeout=300):
    """Run yt-dlp with the shared flags every download path needs
    (no-playlist, force-ipv4, cookies when configured, optional proxy).

    ``args`` are extra CLI arguments (format, extractor-args, output, URL...).
    Returns the CompletedProcess, or None on timeout."""
    cmd = ["yt-dlp", "--no-playlist", "--no-warnings", "--force-ipv4"]
    cmd.extend(args)
    if proxy:
        cmd.extend(["--proxy", proxy])
    cookies = _cookies_arg()
    if cookies:
        cmd.extend(["--cookies", cookies])
    else:
        browser = _cookies_browser_arg()
        if browser:
            cmd.extend(["--cookies-from-browser", browser])
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


def is_bot_check(text):
    """True when yt-dlp output looks like a YouTube bot check / sign-in wall."""
    return any(p in text for p in (
        "Sign in to confirm", "you're not a bot", "you are not a bot",
        "unusual traffic", "sign in to confirm", "Confirm you",
    ))


def _try_download(url, output_dir, proxy):
    """One yt-dlp attempt. Returns (result_dict_or_None, kind) where kind is
    'ok', 'bot_check' or 'error' so the caller can classify failures."""
    output_template = os.path.join(output_dir, "video.%(ext)s")
    args = [
        "--extractor-args", "youtube:player_client=android;formats=duplicate,missing_pot",
        "-f", "best",
        "-o", output_template,
        "--print-json",
        url,
    ]
    result = run_yt_dlp(args, proxy)
    if result is None:
        config.log("yt-dlp download timed out (300s)")
        return None, "error"
    if result.returncode != 0:
        err = (result.stderr or "")[:2000]
        config.log(f"yt-dlp failed: {err[:200]}")
        if is_bot_check(err):
            config.log("bot-check: YouTube flagged the request (IP + no cookies)")
            return None, "bot_check"
        return None, "error"
    info = json.loads(result.stdout) if result.stdout.strip() else {}
    filepath = info.get("filename") or info.get("_filename")
    if filepath and os.path.exists(filepath):
        config.log(f"video downloaded: {filepath}")
        return {"path": filepath, "info": info}, "ok"
    for f in os.listdir(output_dir):
        if f.startswith("video."):
            full = os.path.join(output_dir, f)
            config.log(f"video downloaded: {full}")
            return {"path": full, "info": info}, "ok"
    config.log("yt-dlp finished but no video file found")
    return None, "error"
