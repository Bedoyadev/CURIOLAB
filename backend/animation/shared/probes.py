"""What FFmpeg can measure on a video file, and the final limiter over its sound.

Copied from the repository this engine was born in (the Shorts factory and the documentary
engine it shared code with), so that this project stands on its own.
"""
import json
import re
import subprocess
from pathlib import Path

WIDTH, HEIGHT, MIN_FPS = 1080, 1920, 30
# Integrated loudness a Short is mixed at, and how far from it is still fine.
LOUDNESS_RANGE = (-18.0, -11.0)
MAX_TRUE_PEAK = -0.5


def _run(args: list[str], timeout: int = 180) -> str:
    done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return (done.stdout or "") + (done.stderr or "")

def probe(video: Path) -> dict:
    raw = _run(["ffprobe", "-v", "error", "-show_entries",
                "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "json", str(video)], 30)
    data = json.loads(raw[raw.index("{"):])
    out = {"duration": float(data["format"]["duration"]), "audio": False, "width": 0, "height": 0, "fps": 0.0}
    for s in data["streams"]:
        if s["codec_type"] == "audio":
            out["audio"] = True
        elif s["codec_type"] == "video":
            num, _, den = s["r_frame_rate"].partition("/")
            out.update(width=s["width"], height=s["height"], fps=float(num) / float(den or 1))
    return out

def black_spans(video: Path) -> list[tuple[float, float]]:
    """Stretches of the picture that are black (a missing image or an empty scene)."""
    log = _run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf", "blackdetect=d=0.5:pic_th=0.995:pix_th=0.05",
                "-an", "-f", "null", "-"])
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)]

def loudness(video: Path) -> dict | None:
    log = _run(["ffmpeg", "-hide_banner", "-i", str(video), "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log, re.S)
    if not match:
        return None
    data = json.loads(match.group(0))
    return {"integrated": float(data["input_i"]), "true_peak": float(data["input_tp"])}

def master(video: Path) -> None:
    """The final pass on the sound: a limiter, so a hit landing on a loud syllable never clips.
    The picture is copied untouched. A failure leaves the video as it was rendered."""
    out = video.with_name(video.stem + "_master.mp4")
    run = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c:v", "copy",
                          "-af", "alimiter=limit=0.84:attack=3:release=60:level=disabled", "-c:a", "aac", "-b:a", "256k",
                          str(out)], capture_output=True, text=True, timeout=300)
    if run.returncode == 0 and out.is_file() and out.stat().st_size > 0:
        out.replace(video)
    else:
        out.unlink(missing_ok=True)
