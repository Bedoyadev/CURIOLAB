"""The channel's music and effects, synthesized here (animation/shared/audio.py has the building
blocks). Nothing is downloaded, so there is no third-party licence to track: every sound is the
channel's own.

- musica: a light, curious bed (plucked notes on a major pentatonic over a soft bass), a loop.
- flotar: a rising shimmer, for the moment things lose their weight.
- caer: a soft thud with a rattle, for when they come back down.
- pop: the title coming in.
- cierre: three rising notes, for the closing card.
"""
from pathlib import Path

import numpy as np

from animation.shared.audio import RATE, _echo, _filter, _loop, _norm, _note, _write

LICENSE = "Síntesis propia del canal (sin terceros)"
VERSION = 1
BPM = 96
# C major pentatonic, two octaves (Hz).
SCALE = (261.63, 293.66, 329.63, 392.0, 440.0, 523.25, 587.33, 659.25)
PATTERN = (0, 2, 4, 2, 5, 4, 2, 3, 0, 2, 4, 5, 7, 5, 4, 2)
BASS = (130.81, 130.81, 110.0, 98.0)


def _pluck(freq: float, seconds: float = 0.9) -> np.ndarray:
    k = np.arange(int(RATE * seconds)) / RATE
    return _note(freq, seconds) * np.exp(-k * 3.2)


def make_music(path: Path, bars: int = 16, seed: int = 5) -> None:
    rng = np.random.default_rng(seed)
    beat = 60 / BPM
    total = int(RATE * beat * 4 * bars) + RATE * 2
    notes, bass = np.zeros(total), np.zeros(total)
    for bar in range(bars):
        for step in range(8):   # eighth notes
            if rng.random() < 0.22 and step not in (0, 4):
                continue        # rests keep it from sounding like a machine
            degree = PATTERN[(bar * 3 + step * (1 + bar % 2)) % len(PATTERN)]
            tone = _pluck(SCALE[degree]) * (0.6 + 0.4 * rng.random()) * (1.0 if step % 2 == 0 else 0.7)
            start = int((bar * 4 + step * 0.5) * beat * RATE)
            notes[start:start + len(tone)] += tone
        low = _note(BASS[bar % len(BASS)], beat * 3.6)
        start = int(bar * 4 * beat * RATE)
        bass[start:start + len(low)] += low
    mix = 0.75 * _norm(_filter(_echo(notes, 0.31, 0.3, 3), 3800), 1) + 0.5 * _norm(_filter(bass, 420), 1)
    mix = _loop(mix[:int(RATE * beat * 4 * bars) + RATE], 1.0)
    _write(path, 0.55 * _norm(mix, 1), 0.55 * _norm(np.roll(mix, int(RATE * 0.012)), 1))


def make_float(path: Path, seconds: float = 1.8, seed: int = 9) -> None:
    rng = np.random.default_rng(seed)
    k = np.arange(int(RATE * seconds)) / RATE
    rise = np.sin(2 * np.pi * np.cumsum(330 * 2 ** (k / seconds * 1.2)) / RATE)
    shimmer = _filter(rng.standard_normal(len(k)), (2500, 7000), "band") * 0.5
    x = (rise * 0.5 + shimmer) * np.sin(np.pi * k / seconds) ** 1.5
    _write(path, _norm(_echo(x, 0.12, 0.4, 4), 0.6))


def make_fall(path: Path, seed: int = 4) -> None:
    rng = np.random.default_rng(seed)
    k = np.arange(int(RATE * 0.9)) / RATE
    thud = np.sin(2 * np.pi * (70 * k + 60 * (1 - np.exp(-k * 18)) / 18)) * np.exp(-k * 9)
    rattle = _filter(rng.standard_normal(len(k)), (900, 4200), "band") * np.exp(-k * 14) * 0.5
    late = np.roll(rattle, int(RATE * 0.16)) * 0.5
    _write(path, _norm(thud + rattle + late, 0.8))


def make_pop(path: Path) -> None:
    k = np.arange(int(RATE * 0.22)) / RATE
    x = np.sin(2 * np.pi * np.cumsum(420 + 900 * np.exp(-k * 30)) / RATE) * np.exp(-k * 22)
    _write(path, _norm(x, 0.6))


def make_chime(path: Path) -> None:
    out = np.zeros(int(RATE * 2.6))
    for i, freq in enumerate((523.25, 659.25, 783.99)):
        tone = _note(freq, 1.8)
        start = int(RATE * 0.16 * i)
        out[start:start + len(tone)] += tone
    _write(path, _norm(_filter(_echo(out, 0.27, 0.35, 4), 5000), 0.7))


SOUNDS = {"musica": make_music, "flotar": make_float, "caer": make_fall, "pop": make_pop, "cierre": make_chime}
SECONDS = {"flotar": 1.8, "caer": 0.9, "pop": 0.22, "cierre": 2.6}
MUSIC_LOOP_SECONDS = 60 / BPM * 4 * 16


def ensure_sounds(audio_dir: Path) -> dict[str, Path]:
    """The channel's sounds, made the first time they are needed (again when VERSION changes)."""
    folder = audio_dir / f"v{VERSION}"
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, make in SOUNDS.items():
        path = folder / f"{name}.wav"
        if not path.is_file():
            make(path)
        out[name] = path
    return out
