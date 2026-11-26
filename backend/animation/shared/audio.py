"""Building blocks for synthesizing sound with numpy: filters, echoes, struck notes, loops.

Copied from the repository this engine was born in (the Shorts factory and the documentary
engine it shared code with), so that this project stands on its own.
"""
import wave
from pathlib import Path

import numpy as np
from scipy import signal

RATE = 44100


def _write(path: Path, left: np.ndarray, right: np.ndarray | None = None) -> None:
    right = left if right is None else right
    data = np.clip(np.stack([left, right], axis=1), -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((data * 32767).astype("<i2").tobytes())

def _filter(x: np.ndarray, hz, kind: str = "low", order: int = 2) -> np.ndarray:
    return signal.sosfilt(signal.butter(order, hz, btype=kind, fs=RATE, output="sos"), x)

def _echo(x: np.ndarray, delay: float = 0.37, feedback: float = 0.55, taps: int = 7) -> np.ndarray:
    """Repeats that die away: distance, without a reverb library."""
    out = x.copy()
    step = int(RATE * delay)
    for k in range(1, taps + 1):
        if k * step >= len(x):
            break
        out[k * step:] += x[:len(x) - k * step] * feedback ** k
    return out

def _note(freq: float, seconds: float) -> np.ndarray:
    """A soft struck string: the fundamental and a few quieter partials, each dying faster."""
    t = np.arange(int(RATE * seconds)) / RATE
    tone = sum(a * np.sin(2 * np.pi * freq * h * t) * np.exp(-t * d)
               for h, a, d in ((1, 1.0, 1.1), (2, 0.42, 1.8), (3, 0.16, 2.6), (4.02, 0.07, 3.4)))
    return tone * np.minimum(1, t / 0.012)   # no click on the attack

def _norm(x: np.ndarray, peak: float) -> np.ndarray:
    return peak * x / max(np.abs(x).max(), 1e-9)

def _loop(x: np.ndarray, seconds: float = 1.5) -> np.ndarray:
    """Blend the end into the start, so the sound repeats without a seam."""
    n = int(RATE * seconds)
    fade = np.linspace(0, 1, n)
    head = x[:n] * fade + x[-n:] * (1 - fade)
    return np.concatenate([head, x[n:-n]])
