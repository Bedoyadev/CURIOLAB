"""Lip sync: which mouth the character shows on every video frame of a line.

Mouth states (drawn by animator/core/character_rig.gd):
    0 closed · 1 slightly open (consonants) · 2 «e» · 3 «a» · 4 «o/u» (round) · 5 «i» (wide, low)

Two tracks, the second built on the first:

- mouth_track: from the audio alone. The mouth opens with the loudness of the voice (states 0-3),
  is closed outside the words, and never holds a state for a single frame. It is what a line gets
  when its words could not be timed.
- viseme_track: the shape of each sound. Inside each word's time, its letters are laid out in
  order (Spanish spelling is close to its sounds: vowels get their shape and most of the time,
  m/b/p close the lips, the other consonants leave them ajar) and the loudness still decides when
  the mouth is shut. These are estimated visemes: the provider's times are per word, not per
  phoneme, and are not treated as phonemes. A forced aligner can replace this function later; the
  renderer only receives the list of states.
"""
import unicodedata
import wave
from pathlib import Path

import numpy as np

# Share of the line's loud level from which the mouth is small / half / wide open.
THRESHOLDS = (0.12, 0.38, 0.68)
WORD_MARGIN = 0.04
MIN_GAP = 0.09
# Below this share of the loud level nothing is being voiced, whatever the letter says.
SILENT = 0.07
VOWELS = {"a": 3, "e": 2, "i": 5, "o": 4, "u": 4}
LIPS = set("mbp")
VOWEL_WEIGHT, CONSONANT_WEIGHT = 2.2, 1.0


def _samples(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"se esperaba audio de 16 bits: {path}")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768
    return (data.reshape(-1, channels).mean(axis=1) if channels > 1 else data), rate


def envelope(path: Path, fps: int) -> list[float]:
    """Loudness per video frame, 0-1 relative to the line's loud level."""
    data, rate = _samples(path)
    hop = rate / fps
    frames = int(np.ceil(len(data) / hop))
    rms = np.array([np.sqrt(np.mean(data[int(i * hop):int((i + 1) * hop)] ** 2)) if int(i * hop) < len(data) else 0.0
                    for i in range(frames)])
    loud = np.percentile(rms, 95) if frames else 0.0
    return [] if loud <= 1e-6 else list(np.clip(rms / loud, 0, 1))


def _no_flicker(states: list[int]) -> list[int]:
    """A state that lasts one frame takes its neighbours' value."""
    for f in range(1, len(states) - 1):
        if states[f - 1] == states[f + 1] != states[f]:
            states[f] = states[f - 1]
    return [int(s) for s in states]


def mouth_track(path: Path, fps: int, words: list[dict] | None = None) -> list[int]:
    levels = envelope(path, fps)
    states = [sum(level >= th for th in THRESHOLDS) for level in levels]
    if words:
        speaking = [False] * len(states)
        for i, w in enumerate(words):
            end = w["end"]
            # Words said in one breath keep the mouth moving; a real pause closes it.
            if i + 1 < len(words) and words[i + 1]["start"] - end < MIN_GAP:
                end = words[i + 1]["start"]
            for f in range(max(0, int((w["start"] - WORD_MARGIN) * fps)), min(len(states), int((end + WORD_MARGIN) * fps) + 1)):
                speaking[f] = True
        states = [s if on else 0 for s, on in zip(states, speaking)]
        # Inside a word the mouth is never fully shut for long: a quiet consonant is not a pause.
        for w in words:
            a, b = int(w["start"] * fps) + 1, int(w["end"] * fps) - 1
            for f in range(max(a, 0), min(b, len(states))):
                states[f] = max(states[f], 1)
    return _no_flicker(states)


def word_shapes(word: str) -> list[tuple[int, float]]:
    """(mouth state, share of the word's time) for each sound of a Spanish word, in order."""
    plain = "".join(c for c in unicodedata.normalize("NFD", word.casefold()) if not unicodedata.combining(c) or c == "̃")
    letters = [c for c in plain.replace("ñ", "ñ") if c.isalpha()]
    shapes: list[tuple[int, float]] = []
    for i, c in enumerate(letters):
        nxt = letters[i + 1] if i + 1 < len(letters) else ""
        if c == "h":
            continue                                    # silent
        if c == "u" and i > 0 and letters[i - 1] in "qg" and nxt in ("e", "i"):
            continue                                    # que, gui: the u is not said
        if c in VOWELS:
            shapes.append((VOWELS[c], VOWEL_WEIGHT))
        elif c == "y" and not nxt:
            shapes.append((5, VOWEL_WEIGHT))            # «y», «muy»: it sounds as an i
        elif c in LIPS:
            shapes.append((0, CONSONANT_WEIGHT))
        else:
            shapes.append((1, CONSONANT_WEIGHT))
    if not shapes:
        return [(1, 1.0)]                               # a figure or a symbol: it is said somehow
    total = sum(w for _, w in shapes)
    return [(s, w / total) for s, w in shapes]


def viseme_track(path: Path, fps: int, words: list[dict]) -> list[int]:
    levels = envelope(path, fps)
    states = [0] * len(levels)
    for w in words:
        start, length = w["start"], max(w["end"] - w["start"], 1 / fps)
        at = start
        for shape, share in word_shapes(w["word"]):
            for f in range(int(round(at * fps)), int(round((at + share * length) * fps))):
                if 0 <= f < len(states):
                    states[f] = shape
            at += share * length
    for f, level in enumerate(levels):
        if level < SILENT:
            states[f] = 0                               # nothing is heard: the mouth is shut
        elif states[f] == 3 and level < THRESHOLDS[1]:
            states[f] = 2                               # an «a» said softly does not open wide
    return _no_flicker(states)


def track(path: Path, fps: int, words: list[dict] | None) -> list[int]:
    """The best track the line allows: shapes by sound when its words are timed, loudness otherwise."""
    return viseme_track(path, fps, words) if words else mouth_track(path, fps)
