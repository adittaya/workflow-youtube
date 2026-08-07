import os
import random
import hashlib
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path

import config

DATA_DIR = Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror")))
BGM_DIR = DATA_DIR / "bgm"
YT_BGM_SUBDIR = BGM_DIR / "yt_downloads"

BUILTIN_TRACKS = [
    {
        "title": "Inspiring Cinematic",
        "genre": "cinematic",
        "mood": "inspiring",
        "url": "https://cdn.pixabay.com/audio/2022/10/25/audio_2af0e79fbe.mp3",
    },
    {
        "title": "Upbeat Corporate",
        "genre": "corporate",
        "mood": "upbeat",
        "url": "https://cdn.pixabay.com/audio/2022/10/25/audio_4a3e1c8b3b.mp3",
    },
    {
        "title": "Ambient Relaxation",
        "genre": "ambient",
        "mood": "relaxing",
        "url": "https://cdn.pixabay.com/audio/2022/11/22/audio_d0ef984e35.mp3",
    },
    {
        "title": "Lo-Fi Study",
        "genre": "lofi",
        "mood": "chill",
        "url": "https://cdn.pixabay.com/audio/2022/05/27/audio_1808fbf07a.mp3",
    },
    {
        "title": "Energetic Rock",
        "genre": "rock",
        "mood": "energetic",
        "url": "https://cdn.pixabay.com/audio/2022/10/18/audio_710e1f5b46.mp3",
    },
]


def ensure_bgm_dir():
    BGM_DIR.mkdir(parents=True, exist_ok=True)


def download_bgm(url, filename=None):
    ensure_bgm_dir()
    if filename is None:
        filename = urllib.parse.urlparse(url).path.split("/")[-1]
    if not filename.endswith((".mp3", ".wav", ".ogg", ".m4a")):
        filename += ".mp3"

    dest = BGM_DIR / filename
    if dest.exists():
        return str(dest)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "yt-mirror/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            dest.write_bytes(resp.read())
        return str(dest)
    except Exception:
        return None


def ensure_bgm_library():
    ensure_bgm_dir()
    existing = list(BGM_DIR.glob("*.mp3")) + list(BGM_DIR.glob("*.wav"))
    if len(existing) >= 3:
        return

    for track in BUILTIN_TRACKS:
        dest = BGM_DIR / f"{track['title'].lower().replace(' ', '_')}.mp3"
        if not dest.exists():
            download_bgm(track["url"], dest.name)


def _pick_from_dir(directory, target_duration):
    """Pick the track in `directory` whose length best matches target_duration.
    Scans top-level audio files only (never descends into subdirs like
    yt_downloads/). Returns None when the directory has no audio files."""
    directory = Path(directory)
    if not directory.is_dir():
        return None
    files = list(directory.glob("*.mp3")) + list(directory.glob("*.wav")) \
        + list(directory.glob("*.ogg")) + list(directory.glob("*.m4a")) \
        + list(directory.glob("*.flac"))
    if not files:
        return None

    best = None
    best_diff = float("inf")

    for f in files:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries",
                 "format=duration", "-of", "csv=p=0", str(f)],
                capture_output=True, text=True
            )
            dur = float(result.stdout.strip() or "0")
            diff = abs(dur - target_duration)
            if diff < best_diff:
                best_diff = diff
                best = f
        except Exception:
            continue

    return str(best) if best else str(random.choice(files))


def get_bgm_for_duration(target_duration):
    """Builtin royalty-free library: download the whitelist, pick a match."""
    ensure_bgm_dir()
    ensure_bgm_library()
    return _pick_from_dir(BGM_DIR, target_duration)


def download_bgm_from_youtube(url, filename=None):
    """Download the audio of a copyright-free music video via yt-dlp and use it
    as the BGM. The file lands in ~/.yt-mirror/bgm/yt_downloads/ so it is never
    picked up by the builtin/local library selection. Returns the file path or
    None on failure."""
    if not url:
        return None
    import download_helpers
    ensure_bgm_dir()
    YT_BGM_SUBDIR.mkdir(parents=True, exist_ok=True)
    if filename is None:
        filename = f"bgm_{hashlib.md5(url.encode('utf-8')).hexdigest()[:12]}"

    try:
        import proxy_pool
        proxy_pool.ensure_working()
    except Exception:
        pass

    out_template = str(YT_BGM_SUBDIR / f"{filename}.%(ext)s")
    args = [
        "--extractor-args", "youtube:player_client=android;formats=duplicate,missing_pot",
        "-f", "bestaudio/best",
        "-x", "--audio-format", "m4a", "--audio-quality", "0",
        "-o", out_template, url,
    ]
    proxies = download_helpers.get_proxy_candidates() or [""]
    for i, proxy in enumerate(proxies):
        config.log(f"bgm yt-dlp attempt {i + 1}/{len(proxies)}"
                   + (f" with proxy: {proxy}" if proxy else " (direct)"))
        result = download_helpers.run_yt_dlp(args, proxy)
        if result is not None and result.returncode == 0:
            candidates = list(YT_BGM_SUBDIR.glob(f"{filename}.*"))
            for c in candidates:
                if c.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a", ".flac") \
                        and c.stat().st_size > 0:
                    config.log(f"bgm downloaded: {c}")
                    return str(c)
        else:
            err = (result.stderr or "")[:200] if result is not None else "timeout"
            config.log(f"bgm download failed: {err}")
    return None


def resolve_bgm(source, target_duration, settings=None):
    """Resolve a BGM track based on the `bgm_source` setting:
      - none    → None (vocals-only audio, nothing mixed in)
      - yt_link → download the audio from bgm_yt_url (copyright-free link the
                  user supplied during Quick Deploy)
      - builtin → whitelisted royalty-free library
      - local   → user's own royalty-free folder (bgm_dir) or ~/.yt-mirror/bgm
    Returns the track path or None (never mixes in unverified random files)."""
    source = (source or "none").strip().lower()
    if source == "none":
        return None

    if source == "yt_link":
        settings = settings or {}
        url = (settings.get("bgm_yt_url") or "").strip()
        if not url:
            return None
        return download_bgm_from_youtube(url)

    if source == "builtin":
        return get_bgm_for_duration(target_duration)

    if source == "local":
        settings = settings or {}
        directory = (settings.get("bgm_dir") or "").strip() or BGM_DIR
        return _pick_from_dir(directory, target_duration)

    return None


def trim_bgm(bgm_path, duration, output_path=None):
    bgm_path = Path(bgm_path)
    if output_path is None:
        output_path = BGM_DIR / f"trimmed_{bgm_path.stem}.wav"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fade_out_start = max(0, duration - 3)
    cmd = [
        "ffmpeg", "-y", "-stream_loop", "-1",
        "-i", str(bgm_path),
        "-t", f"{duration + 1}",
        "-af", f"afade=t=in:st=0:d=2,afade=t=out:st={fade_out_start}:d=3",
        "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
        str(output_path)
    ]
    subprocess.run(cmd, capture_output=True, text=True)
    return str(output_path)
