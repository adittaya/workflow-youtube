import json
import os
import random
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path

DATA_DIR = Path(os.environ.get("YT_DATA_DIR", os.path.expanduser("~/.yt-mirror")))
BGM_DIR = DATA_DIR / "bgm"
BGM_INDEX = DATA_DIR / "bgm_index.json"

YT_AUDIO_LIBRARY_API = "https://thibaultjanbeyer.github.io/YouTube-Free-Audio-Library-API/api.json"

FREESOUND_SEARCH = "https://freesound.org/apiv2/search/text/"

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


def load_index():
    if BGM_INDEX.exists():
        try:
            return json.loads(BGM_INDEX.read_text("utf-8"))
        except Exception:
            pass
    return {"tracks": [], "last_fetch": 0}


def save_index(index):
    BGM_INDEX.parent.mkdir(parents=True, exist_ok=True)
    BGM_INDEX.write_text(json.dumps(index, indent=2), "utf-8")


def fetch_youtube_audio_library():
    try:
        req = urllib.request.Request(
            YT_AUDIO_LIBRARY_API,
            headers={"User-Agent": "yt-mirror/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return data if isinstance(data, list) else data.get("tracks", [])
    except Exception:
        return []


def fetch_freesound(api_key, query="background music", duration_max=180):
    try:
        params = urllib.parse.urlencode({
            "query": query,
            "filter": f"duration:[* TO {duration_max}]",
            "fields": "id,name,previews,download,duration,license",
            "page_size": 10,
        })
        url = f"{FREESOUND_SEARCH}?{params}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Token {api_key}",
            "User-Agent": "yt-mirror/1.0"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return data.get("results", [])
    except Exception:
        return []


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


def get_random_bgm():
    ensure_bgm_dir()
    ensure_bgm_library()

    files = list(BGM_DIR.glob("*.mp3")) + list(BGM_DIR.glob("*.wav"))
    if not files:
        return None
    return str(random.choice(files))


def get_bgm_for_duration(target_duration):
    ensure_bgm_dir()
    ensure_bgm_library()

    files = list(BGM_DIR.glob("*.mp3")) + list(BGM_DIR.glob("*.wav"))
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
