import subprocess
import os
import tempfile
from pathlib import Path

TEMP_DIR = Path(os.environ.get("YT_TEMP_DIR", "/tmp/yt-process"))

DEMUCS_AVAILABLE = None


def _check_demucs():
    global DEMUCS_AVAILABLE
    if DEMUCS_AVAILABLE is not None:
        return DEMUCS_AVAILABLE
    try:
        result = subprocess.run(
            ["python3", "-c", "import demucs; print('ok')"],
            capture_output=True, text=True, timeout=10
        )
        DEMUCS_AVAILABLE = result.returncode == 0
    except Exception:
        DEMUCS_AVAILABLE = False
    return DEMUCS_AVAILABLE


def _run(cmd, desc=""):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed ({desc}): {result.stderr[:500]}")
    return result


def extract_audio(video_path, output_path=None):
    if output_path is None:
        output_path = TEMP_DIR / "extracted_audio.wav"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "44100", "-ac", "2",
        str(output_path)
    ]
    _run(cmd, "extract_audio")
    return output_path


def separate_vocals_demucs(audio_path, output_dir=None, model="htdemucs"):
    output_dir = Path(output_dir or TEMP_DIR / "separated")
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = Path(audio_path)

    cmd = [
        "demucs", "-n", model,
        "--two-stems", "vocals",
        "-o", str(output_dir),
        str(audio_path)
    ]
    _run(cmd, "demucs_separate")

    song_stem = audio_path.stem
    stem_dir = output_dir / model / song_stem

    vocals = stem_dir / "vocals.wav"
    instrumental = stem_dir / "no_vocals.wav"

    if not vocals.exists():
        for f in stem_dir.glob("*.wav"):
            if "vocal" in f.name.lower():
                vocals = f
            else:
                instrumental = f

    return {
        "vocals": str(vocals) if vocals.exists() else None,
        "instrumental": str(instrumental) if instrumental.exists() else None,
        "stem_dir": str(stem_dir),
    }


def separate_vocals_ffmpeg(audio_path, output_dir=None):
    output_dir = Path(output_dir or TEMP_DIR / "separated")
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = Path(audio_path)

    vocals_path = output_dir / f"{audio_path.stem}_vocals.wav"
    instrumental_path = output_dir / f"{audio_path.stem}_instrumental.wav"

    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-af", "pan=stereo|c0=c0-c1|c1=c0-c1",
        str(vocals_path)
    ]
    _run(cmd, "ffmpeg_vocals")

    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-af", "stereotools=mlev=0.5:mpan=0",
        str(instrumental_path)
    ]
    _run(cmd, "ffmpeg_instrumental")

    return {
        "vocals": str(vocals_path) if vocals_path.exists() else None,
        "instrumental": str(instrumental_path) if instrumental_path.exists() else None,
        "stem_dir": str(output_dir),
    }


def separate_vocals(audio_path, output_dir=None, model="htdemucs"):
    if _check_demucs():
        try:
            return separate_vocals_demucs(audio_path, output_dir, model)
        except Exception:
            pass

    return separate_vocals_ffmpeg(audio_path, output_dir)


def separate_video_audio(video_path, output_dir=None, model="htdemucs"):
    audio_path = extract_audio(video_path)
    return separate_vocals(audio_path, output_dir, model)


def replace_audio(video_path, new_audio_path, output_path):
    video_path = Path(video_path)
    new_audio_path = Path(new_audio_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(new_audio_path),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest",
        str(output_path)
    ]
    _run(cmd, "replace_audio")
    return output_path


def mix_audio(video_path, new_audio_path, output_path,
              original_vol=0.8, bgm_vol=0.25):
    video_path = Path(video_path)
    new_audio_path = Path(new_audio_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    filter_complex = (
        f"[0:a]volume={original_vol}[v];"
        f"[1:a]volume={bgm_vol}[b];"
        f"[v][b]amix=inputs=2:duration=first:"
        f"dropout_transition=0:normalize=0[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(new_audio_path),
        "-filter_complex", filter_complex,
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        str(output_path)
    ]
    _run(cmd, "mix_audio")
    return output_path


def remove_bgm_keep_vocals(video_path, output_video_path=None,
                            output_dir=None, model="htdemucs"):
    output_dir = Path(output_dir or TEMP_DIR / "vocal_extract")
    output_dir.mkdir(parents=True, exist_ok=True)

    video_path = Path(video_path)
    stems = separate_video_audio(video_path, output_dir, model)

    if not stems["vocals"]:
        raise RuntimeError("Vocal separation failed")

    if output_video_path is None:
        output_video_path = output_dir / f"{video_path.stem}_vocals_only.mp4"
    output_video_path = Path(output_video_path)

    replace_audio(video_path, stems["vocals"], output_video_path)

    return {
        "video": str(output_video_path),
        "vocals": stems["vocals"],
        "instrumental": stems["instrumental"],
    }
