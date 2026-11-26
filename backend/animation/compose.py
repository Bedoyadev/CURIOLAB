"""Composition Engine: the scenes Godot drew, the recorded lines, the captions, the music and the
effects become one MP4 (1080×1920, 30 fps, H.264).

- FFmpeg has already turned each scene into an MP4 of its exact length (godot.py); here the lines
  are mixed into one dialogue track, each at the second its beat starts.
- FFmpeg joins the scenes end to end without re-encoding them.
- Remotion (renderer/src/animation) renders only what goes over them, on a transparent background: the title, the
  captions, the on-screen labels and the closing card, with the whole sound mix (voices, music
  under them, effects). The browser never decodes the scenes, which is what made this step slow.
- FFmpeg lays that layer over the joined scenes and encodes the final H.264, and its limiter
  passes over the sound (shared.probes.master).
"""
import asyncio
import subprocess
import wave
from pathlib import Path

import numpy as np

from animation import sound
from animation.library import Library
from animation.profile import AnimationProfile
from animation.shared.probes import master
from animation.shared.remotion import RemotionRenderer, RenderOutput

ENTRY = "src/animation/index.ts"
COMPOSITION = "AnimOverlay"
THUMBNAIL = "AnimThumb"
# The layer keeps its transparency: ProRes 4444 from PNG frames.
OVERLAY_FLAGS = ["--codec=prores", "--prores-profile=4444", "--image-format=png", "--pixel-format=yuva444p10le"]
RATE = 44100
TAIL_SECONDS = 3.6
MUSIC_VOLUME, EFFECT_VOLUME = 0.14, 0.45


def _read(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != RATE or w.getsampwidth() != 2:
            raise ValueError(f"audio con formato inesperado: {path}")
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
        return data.reshape(-1, w.getnchannels()).mean(axis=1) if w.getnchannels() > 1 else data


def mix_dialogue(lines: list[dict], duration: float, out: Path) -> Path:
    """Every line at its second, in one track as long as the episode."""
    track = np.zeros(int(RATE * duration) + RATE)
    for line in lines:
        data = _read(Path(line["path"]))
        start = int(RATE * line["start"])
        end = min(len(track), start + len(data))
        track[start:end] += data[:end - start]
    track = np.clip(track[:int(RATE * duration)], -1, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((track * 32767).astype("<i2").tobytes())
    return out


def sound_cues(timeline: dict, sounds: dict[str, Path]) -> list[dict]:
    """Effects placed from what happens in the scenes."""
    def shot(name: str, at: float) -> dict:
        return {"src": f"sonido/{name}.wav", "at": round(max(0.0, at), 3), "seconds": sound.SECONDS[name], "volume": EFFECT_VOLUME}

    cues = [shot("pop", 0.15)] if "pop" in sounds else []
    for scene in timeline["scenes"]:
        for e in scene["plan"]["events"]:
            if e["type"] != "effect":
                continue
            if e["effect"] == "gravity_off" and "flotar" in sounds:
                cues.append(shot("flotar", scene["start"] + e["t"]))
            elif e["effect"] == "gravity_on" and "caer" in sounds:
                cues.append(shot("caer", scene["start"] + e["t"] + 0.22))
    if "cierre" in sounds:
        cues.append(shot("cierre", timeline["duration"] + 0.1))
    return cues


def build_props(profile: AnimationProfile, lib: Library, title: str, timeline: dict, videos: list[Path],
                sounds: dict[str, Path]) -> tuple[dict, dict[str, Path]]:
    """(props of the composition, the files it needs by their public path)."""
    media: dict[str, Path] = {}
    scenes = []
    for i, (scene, video) in enumerate(zip(timeline["scenes"], videos)):
        rel = f"media/escena_{i:02d}.mp4"
        media[rel] = Path(video)
        scenes.append({"src": rel, "start": scene["start"], "duration": scene["duration"], "label": scene["label"]})
    for name, path in sounds.items():
        media[f"sonido/{name}.wav"] = path
    speakers = {}
    for cid in sorted({w["speaker"] for w in timeline["words"]}):
        look = lib.characters[cid]["appearance"]
        speakers[cid] = {"name": lib.characters[cid]["name"], "color": look.get("shirt") or look.get("accent") or profile.brand.accent}
    # The cover: the longest scene with characters on stage, a little past its middle.
    staged = [s for s in timeline["scenes"] if s["plan"]["characters"]] or timeline["scenes"]
    cover = max(staged, key=lambda s: s["duration"])
    b = profile.brand
    props = {
        "brand": {"ink": b.ink, "paper": b.paper, "accent": b.accent, "accent2": b.accent2},
        "channel": profile.name, "slogan": profile.slogan, "closingLine": profile.closing_line, "subscribe": profile.subscribe,
        "title": title, "scenes": scenes, "words": timeline["words"], "speakers": speakers,
        "audio": "audio/narration.wav",
        "music": {"src": "sonido/musica.wav", "volume": MUSIC_VOLUME, "loopSeconds": sound.MUSIC_LOOP_SECONDS} if "musica" in sounds else None,
        "shots": sound_cues(timeline, sounds),
        "durationSeconds": timeline["duration"], "tailSeconds": TAIL_SECONDS,
        "thumb": {"src": f"media/escena_{timeline['scenes'].index(cover):02d}.mp4", "at": round(cover["duration"] * 0.6, 2)},
    }
    return props, media


class ComposeFailed(Exception):
    pass


def _ffmpeg(args: list[str], what: str, timeout: int = 900) -> None:
    run = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=timeout)
    if run.returncode != 0:
        raise ComposeFailed(f"ffmpeg no pudo {what}: {run.stderr[-400:]}")


def join_scenes(videos: list[Path], out: Path) -> Path:
    """The scenes end to end. They come from the same encoder with the same settings, so they are
    joined without touching a frame."""
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{Path(v).resolve().as_posix()}'\n" for v in videos), encoding="utf-8")
    try:
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)], "unir las escenas")
    finally:
        listing.unlink(missing_ok=True)
    return out


def lay_over(base: Path, overlay: Path, out: Path, tail: float, fps: int = 30) -> Path:
    """The layer over the scenes. The last frame of the scenes is held under the closing card."""
    graph = (f"[0:v]tpad=stop_mode=clone:stop_duration={tail + 1:.2f}[base];"
             f"[base][1:v]overlay=shortest=1:format=auto,format=yuv420p[v]")
    _ffmpeg(["-i", str(base), "-i", str(overlay), "-filter_complex", graph, "-map", "[v]", "-map", "1:a",
             "-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "256k",
             "-movflags", "+faststart", str(out)], "montar el video final")
    return out


async def render(props: dict, media: dict[str, Path], dialogue: Path, out_dir: Path, renderer: RemotionRenderer | None = None) -> RenderOutput:
    renderer = renderer or RemotionRenderer(entry=ENTRY, render_flags=OVERLAY_FLAGS)
    videos = [media[s["src"]] for s in props["scenes"]]
    base = await asyncio.to_thread(join_scenes, videos, out_dir / "escenas_unidas.mp4")
    layer = await renderer.render(props, media, dialogue, out_dir, composition=COMPOSITION, stills={THUMBNAIL: "miniatura.png"},
                                  video_name="capa.mov")
    video = out_dir / "short.mp4"
    try:
        await asyncio.to_thread(lay_over, base, layer.video, video, props["tailSeconds"])
    finally:
        # Intermediate files, several times the size of the result.
        base.unlink(missing_ok=True)
        layer.video.unlink(missing_ok=True)
    await asyncio.to_thread(master, video)
    return RenderOutput(video, layer.thumbnail)
