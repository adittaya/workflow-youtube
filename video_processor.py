import subprocess
import os
import random
import hashlib
import json
from pathlib import Path

TEMP_DIR = Path(os.environ.get("YT_TEMP_DIR", "/tmp/yt-process"))


def _run(cmd, desc=""):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed ({desc}): {result.stderr[:500]}")
    return result


def get_video_info(path):
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path)
    ]
    result = _run(cmd, "probe")
    return json.loads(result.stdout)


def get_video_hash(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def apply_edits(input_path, output_path, edits=None):
    if edits is None:
        edits = _random_edit_preset()

    info = get_video_info(input_path)
    duration = float(info.get("format", {}).get("duration", 60))
    width, height = _get_resolution(info)

    trim_start = float(edits.get("trim_start", 0) or 0)
    trim_end = float(edits.get("trim_end", 0) or 0)
    out_duration = max(1.0, duration - trim_start - trim_end)

    filters = []
    audio_filters = []

    if edits.get("crop"):
        cw, ch = edits["crop"]
        if cw > width:
            cw = int(width * 0.92)
        if ch > height:
            ch = int(height * 0.92)
        x = (width - cw) // 2
        y = (height - ch) // 2
        filters.append(f"crop={cw}:{ch}:{x}:{y}")

    if edits.get("scale"):
        sw, sh = edits["scale"]
        if sw > width or sh > height:
            sw = min(sw, width)
            sh = min(sh, height)
        filters.append(f"scale={sw}:{sh}")

    if edits.get("speed") and edits["speed"] != 1.0:
        speed = edits["speed"]
        filters.append(f"setpts={1/speed}*PTS")
        audio_filters.append(f"atempo={speed}")

    if edits.get("flip"):
        filters.append("hflip")

    if edits.get("rotate"):
        angle = edits["rotate"]
        filters.append(f"rotate={angle}:fillcolor=black")

    if edits.get("grain"):
        strength = edits.get("grain_strength", 8)
        filters.append(f"noise=alls={strength}:allf=t")

    if edits.get("brightness"):
        b = edits["brightness"]
        filters.append(f"eq=brightness={b}")

    if edits.get("contrast"):
        c = edits["contrast"]
        filters.append(f"eq=contrast={c}")

    if edits.get("fps"):
        try:
            fps = int(edits["fps"])
            if fps >= 1:
                filters.append(f"fps={fps}")
        except (TypeError, ValueError):
            pass

    if edits.get("text_overlay"):
        text = edits["text_overlay"]
        fontsize = edits.get("fontsize", 36)
        color = edits.get("text_color", "white")
        x = edits.get("text_x", "(w-text_w)/2")
        y = edits.get("text_y", "h-th-30")
        enable = edits.get("text_enable", "between(t,2,7)")
        filters.append(
            f"drawtext=text='{text}':fontsize={fontsize}:fontcolor={color}"
            f":x={x}:y={y}:enable='{enable}'"
        )

    if edits.get("fade_in"):
        d = edits["fade_in"]
        filters.append(f"fade=t=in:st=0:d={d}")

    if edits.get("fade_out"):
        d = edits["fade_out"]
        start = max(0, out_duration - d)
        filters.append(f"fade=t=out:st={start}:d={d}")

    cmd = ["ffmpeg", "-y"]
    if trim_start > 0:
        cmd.extend(["-ss", f"{trim_start:g}"])
    cmd.extend(["-i", str(input_path)])

    vf = ",".join(filters) if filters else None
    af = ",".join(audio_filters) if audio_filters else None

    if vf:
        cmd.extend(["-vf", vf])
    if af:
        cmd.extend(["-af", af])

    cmd.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
    ])
    if trim_start > 0 or trim_end > 0:
        cmd.extend(["-t", f"{out_duration:g}"])
    cmd.append(str(output_path))

    _run(cmd, "edit")
    return output_path


def _get_resolution(info):
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            return int(s.get("width", 1920)), int(s.get("height", 1080))
    return 1920, 1080


def _random_edit_preset():
    presets = [
        {
            "name": "subtle_crop",
            "crop": (1780, 1000),
            "speed": round(random.uniform(0.97, 1.03), 2),
            "grain": True,
            "grain_strength": random.randint(5, 12),
            "brightness": round(random.uniform(-0.03, 0.03), 3),
            "fade_in": 0.5,
            "fade_out": 1.0,
        },
        {
            "name": "scale_shift",
            "scale": (1920, 1080),
            "speed": round(random.uniform(0.98, 1.02), 2),
            "grain": True,
            "grain_strength": random.randint(4, 10),
            "contrast": round(random.uniform(0.98, 1.05), 3),
            "fade_in": 0.8,
            "fade_out": 1.5,
        },
        {
            "name": "flip_crop",
            "flip": True,
            "crop": (1800, 1020),
            "speed": round(random.uniform(0.96, 1.04), 2),
            "grain": True,
            "grain_strength": random.randint(6, 14),
            "brightness": round(random.uniform(-0.02, 0.02), 3),
            "fade_in": 0.3,
            "fade_out": 1.0,
        },
        {
            "name": "zoom_crop",
            "crop": (1700, 960),
            "scale": (1920, 1080),
            "speed": round(random.uniform(0.97, 1.03), 2),
            "grain": True,
            "grain_strength": random.randint(5, 10),
            "fade_in": 0.5,
            "fade_out": 1.2,
        },
        {
            "name": "rotate_subtle",
            "rotate": round(random.uniform(-0.02, 0.02), 4),
            "crop": (1780, 1000),
            "scale": (1920, 1080),
            "speed": round(random.uniform(0.98, 1.02), 2),
            "grain": True,
            "grain_strength": random.randint(4, 8),
            "fade_in": 0.4,
            "fade_out": 1.0,
        },
    ]

    preset = random.choice(presets)
    preset.pop("name", None)
    return preset


def preset_edits(extra=None):
    """Random anti-Content-ID preset plus optional processing overrides
    (fps, trim_start, trim_end, ...). The random crop/speed/grain edits keep
    the video distinguishable from the source; the overrides apply on top."""
    edits = _random_edit_preset()
    if extra:
        edits.update(extra)
    return edits
